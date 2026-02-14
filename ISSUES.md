# Engrammar Issues

## Concept / Product-Level — Redesign: Tag-Relevance Scoring

Issues #1–#4 are resolved together by replacing the current evaluation system with a
**per-tag relevance scoring** model, evaluated via `claude -p` on SessionStart (no API key needed).

### Design

**Problem**: Current SessionEnd hook evaluates usefulness with almost no context, fails open
to "everything is useful", and feeds a positive-only auto-pin loop.

**Solution**: Three-layer feedback system:

1. **In-session (active)**: Lessons are shown with `EG#ID` markers in machine-readable blocks.
   MCP instructions tell the model to call `engrammar_feedback` when a lesson doesn't apply.
2. **SessionEnd (audit)**: Persist a lightweight audit record (session_id, shown_lesson_ids,
   env_tags, repo, timestamp) then clear session state. No heavy evaluation.
3. **SessionStart (async eval)**: Background process reads audit records from previous sessions,
   calls `claude -p --model haiku` (user's subscription, no API key) with the full transcript +
   audit data, outputs per-tag relevance scores.

#### Hook Output Format

Hooks output lessons in a structured, parseable block with stable ID markers:

```
[ENGRAMMAR_V1]
- [EG#42][development/frontend] Never use inline styles — use CSS classes or Picasso props
- [EG#17][development/git] Branch naming: taps-NUMBER (lowercase)
Treat these as soft constraints. If one doesn't apply here, call engrammar_feedback(lesson_id, applicable=false, reason="...").
[/ENGRAMMAR_V1]
```

This gives the model actionable IDs for feedback. The async evaluator should use
`session_audit` as the deterministic source of shown lesson IDs, with transcript parsing
used as optional context.

#### MCP Server Instructions

Add to the MCP `instructions` field:

> When lessons are shown via `[ENGRAMMAR_V1]` blocks, treat them as soft constraints.
> If a lesson doesn't apply to the current context, call `engrammar_feedback` with the
> lesson_id and reason. This helps Engrammar learn when to surface lessons.

This creates passive negative feedback from normal sessions without requiring a skill.

#### New Tables

**`lesson_tag_relevance`** — per-tag scoring:

```sql
CREATE TABLE lesson_tag_relevance (
    lesson_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    score REAL DEFAULT 0.0,           -- accumulated, clamped to [-3.0, 3.0]
    positive_evals INTEGER DEFAULT 0,
    negative_evals INTEGER DEFAULT 0,
    last_evaluated TEXT,
    PRIMARY KEY (lesson_id, tag),
    FOREIGN KEY (lesson_id) REFERENCES lessons(id)
);
```

**`session_audit`** — ground truth for what was shown:

```sql
CREATE TABLE session_audit (
    session_id TEXT PRIMARY KEY,
    shown_lesson_ids TEXT NOT NULL,    -- JSON array of lesson IDs
    env_tags TEXT NOT NULL,            -- JSON array of tags
    repo TEXT,
    timestamp TEXT NOT NULL
);
```

**`processed_relevance_sessions`** — separate from extraction tracking:

```sql
CREATE TABLE processed_relevance_sessions (
    session_id TEXT PRIMARY KEY,
    processed_at TEXT,
    retry_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending'      -- pending | completed | failed
);
```

#### Haiku Agent Output

Per lesson, per tag in that session's environment:

```json
[
  { "lesson_id": 42, "tag_scores": { "typescript": 0.9, "frontend": 0.6 } },
  {
    "lesson_id": 17,
    "tag_scores": { "typescript": -0.5, "backend": -0.8 },
    "reason": "React advice shown in backend context"
  }
]
```

Scores range from -1.0 (actively harmful) to +1.0 (essential).

#### Scoring Math

Accumulated scores use **damping + confidence**:

- **Bounded range**: clamp score to [-3.0, 3.0] per tag
- **Min evidence**: require >= 5 evals before pin/unpin decisions
- **Hysteresis**: pin at avg score > 0.6, unpin at avg score < 0.2
- **Decay**: exponential moving average (EMA) with α=0.3 so recent evals
  weigh more and old signals fade

#### Search Integration

Tag scores become a **normalized** boost/penalty on hybrid search results:

```python
base_score = hybrid_search_score(lesson)  # RRF output
tag_boost = avg(tag_relevance[lesson_id].get(tag, 0) for tag in env_tags)
normalized_boost = tag_boost / MAX_SCORE  # normalize to [−1, 1]
final_score = base_score + (normalized_boost * RELEVANCE_WEIGHT)
```

`RELEVANCE_WEIGHT` tuned small relative to RRF scores to avoid swamping ranking.

#### Auto-Pin/Unpin

Replace threshold counter logic with score-based decisions:

- **Pin** when avg tag score > 0.6 AND total evals >= 5 for specific tags
- **Unpin** when avg tag score < 0.2 (with same min-evidence guard)
- Prerequisites auto-derived from high-scoring tags
- Negative scores actively reduce and can reverse pin status

#### Negative Feedback via MCP

Enhance `engrammar_feedback` to accept optional `tag_scores` dict:

- `engrammar_feedback(lesson_id=17, applicable=false, tag_scores={"java": -1.0})`
- Model can call this during the session when it sees an irrelevant lesson
- Scores from explicit feedback weighted higher than async eval (e.g. 2x)

### Implementation Steps

- [ ] **1a. Add new tables** — `lesson_tag_relevance`, `session_audit`, `processed_relevance_sessions` in `db.py:init_db`. Keep existing `lesson_tag_stats` during transition.
- [ ] **1a.1. Fix shown-state race first** — add file locking/atomic writes for `.session-shown.json` (or move shown tracking to DB events) so `session_audit.shown_lesson_ids` is trustworthy.
- [ ] **1b. Update hook output format** — `[ENGRAMMAR_V1]` block with `EG#ID` markers in `on_prompt.py`, `on_tool_use.py`, `on_session_start.py`. Include behavior instruction line.
- [ ] **1c. Update MCP server instructions** — add guidance about calling `engrammar_feedback` when lessons don't apply.
- [ ] **1d. SessionEnd → audit record** — persist `session_audit` row (session_id, shown_lesson_ids, env_tags, repo, timestamp), clear `.session-shown.json`. Remove all evaluation logic.
- [ ] **1e. Build evaluation runner** — new module that calls `claude -p` with audit record + transcript excerpt, parses structured JSON output. Follow `extractor.py` pattern (remove `CLAUDECODE` env var). Use `processed_relevance_sessions` for tracking with retry support.
- [ ] **1f. Wire evaluation into SessionStart** — run in background. Process unprocessed audit records. Separate from extraction pipeline.
- [ ] **1g. Score accumulation function** — `update_tag_relevance(lesson_id, tag_scores)` in `db.py` with EMA, clamping to [-3, 3], positive/negative counters.
- [ ] **1h. Integrate tag scores into search ranking** — normalized boost/penalty in `search.py`.
- [ ] **1i. Implement auto-pin/unpin** — score-based with hysteresis (pin >0.6, unpin <0.2) and min-evidence guard (>=5 evals).
- [ ] **1j. Enhance `engrammar_feedback` MCP tool** — accept optional `tag_scores` dict, weight explicit feedback higher.
- [ ] **1k. Remove dead evaluation code** — `_evaluate_lesson_usefulness`, Anthropic SDK dependency, old backfill evaluation logic.

### Issues resolved by this redesign

- [x] ~~**1. "Usefulness" evaluation is unreliable by design**~~ → Full transcript + Haiku agent provides rich context.
- [x] ~~**2. Fail-open pattern defeats intelligent matching**~~ → No API key needed (`claude -p` uses subscription). Runtime failures use fail-neutral handling (no score update) with retry + logging.
- [x] ~~**3. Auto-pin positive feedback loop with no brakes**~~ → Negative scores enable auto-unpin. Scoring is bidirectional.
- [x] ~~**4. Fail-open vs fail-closed inconsistency**~~ → Single evaluation path (backfill on SessionStart). No inconsistency.

## Architecture

- [ ] **5. `sys.path.insert(0, ENGRAMMAR_HOME)` everywhere** — Every file manually inserts into sys.path. No `setup.py`/`pyproject.toml`. Code lives in `src/` during development but hooks import from `engrammar.*`. Installation is manual file copying.

- [ ] **6. Race condition on `.session-shown.json`** — `on_prompt.py`, `on_tool_use.py`, and `on_session_end.py` all read/write the same file without locking. Concurrent hooks can silently lose writes.

- [ ] **7. Daemon is single-threaded** — Processes one request at a time. Slow searches block all other hook calls, potentially adding visible latency to Claude Code.

- [ ] **8. Config cached per-process but daemon is long-lived** — `config.py` caches config at module level. For the daemon (runs 15 min), config changes are invisible until restart.

## Code Quality

- [ ] **9. CLI argument parsing is hand-rolled** — Manual `sys.argv` parsing with `while` loops. No help text per command, no validation, no error messages. Only `backfill_stats.py` uses argparse properly.

- [ ] **10. Duplicate utility code across hooks** — `_load_shown`, `_save_shown`, `_log_error` are copy-pasted across 3 hook files with minor variations. No shared utility module.

- [ ] **11. `find_similar_lesson` uses word overlap instead of vectors** — `db.py` uses crude >50% word overlap for dedup. The project has a full vector search system but doesn't use it for semantic similarity detection.

- [ ] **12. Full index rebuild on every lesson add** — `cmd_add` and `engrammar_add` call `build_index(get_all_active_lessons())` after adding one lesson. Re-embeds entire corpus every time.

- [ ] **13. Repo detection in backfill hardcoded to `/work/` paths** — `backfill_stats.py:61-64` only works for one directory layout. Rest of codebase uses `git remote get-url origin`.

- [ ] **14. `datetime.utcnow()` is deprecated** — Used across multiple files. Python 3.12+ deprecates this. `extractor.py` already uses `datetime.now(timezone.utc)` — the rest should too.

- [ ] **15. Connection management in `update_match_stats`** — Commits mid-function then calls `find_auto_pin_tag_subsets` which opens its own connection. Outer function continues using its connection after. Works due to WAL mode but fragile.

- [ ] **16. No input validation on MCP tools** — `engrammar_add` accepts empty text, arbitrary-length strings. No validation on category format.

## Missing / Misleading

- [ ] **17. Test coverage is minimal** — Only narrow regression tests exist. Zero tests for CLI, MCP server, daemon, extractor, or hook integration logic.

- [x] ~~**18. `register_hooks.py` is dead code**~~ — Not dead code. Called by `setup.sh:70` to register hooks in `~/.claude/settings.json` and MCP server in `~/.claude.json`.

- [ ] **19. Errors silently swallowed** — All hooks eat exceptions and log to `.hook-errors.log`. No user-facing feedback when the system breaks. No guided health check. Additionally, `on_session_end.py:119` catches exceptions in `_evaluate_lesson_usefulness` and returns `True` without even calling `_log_error`, unlike every other error path in that file.

- [ ] **20. `test_tag_stats.py` is corrupted — blocks entire test suite** — `tests/test_tag_stats.py` has `lesson_id = cursor.lastrowid` stray lines on many lines, causing `IndentationError` on collection. `pytest tests/` can't run the full suite.

- [ ] **21. Backfill uses current environment for historical sessions** — `backfill_stats.py:115` calls `search()` which calls `detect_environment()` at `search.py:62`, filtering historical session lessons against today's repo/tags. Old sessions from different contexts get wrong prerequisite filtering and skewed match stats.

- [ ] **22. CLI `update --category` doesn't sync level1/level2/level3** — `cli.py:360` updates only the `category` column. The MCP `engrammar_update` does parse and sync `level1`/`level2`/`level3`. Since `get_category_stats()` groups by `level1`, CLI-updated categories drift from stats.

- [ ] **23. Path prerequisite matching false-matches on prefixes** — `environment.py:119` uses `cwd.startswith(path)` which means a prerequisite of `/work/app` would also match `/work/application`. Should use path-boundary-aware comparison (e.g. append `/` before matching).
