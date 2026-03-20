# #39 Drop environment tags as stored signal, introduce content tags, fix extraction

**Severity:** High
**Complexity:** C3

## Problem

`prerequisites.tags` currently stores environment-detected tags (e.g. `react`, `typescript`, `repo:engrammar`, `frontend`, `monorepo`) as both soft scoring features and quasi-hard gates. This creates three problems:

1. **Zero within-repo differentiation**: all engrams from the same repo get identical environment tags, so the tag component (40% of score) adds no signal. Evidence from session `b5ea4009`: EG#167 (forms — relevant) and EG#104 (mainSkillName — noise) score identically.

2. **Environment tags are weak retrieval features**: generic tags like `typescript`, `frontend`, `monorepo` rarely determine whether an engram is relevant. When a tag IS genuinely important (e.g. `react` for a React-specific engram), it's because the engram is *about* React — that's a content tag, not an environment signal.

3. **Pollution path**: the `relevant_tags=[]` fallback in `src/pipeline/extractor.py:588-596` falls back to full env tags when the LLM returns empty, and `_maybe_backfill_prerequisites` (`src/pipeline/extractor.py:225`) only writes when prerequisites are null.

## Design: constraints + content tags + repo prior

Drop environment tags as a stored ranking signal. Keep them only as extraction-time context for the LLM. The model becomes:

- **constraints**: hard applicability gates in `prerequisites` JSON — `repos`, `paths`, `os`, `mcp_servers`. Unchanged.
- **content_tags**: the only tag system for soft topical matching — what the engram is *about* (e.g. `forms`, `tdd`, `authentication`, `react`). New `engram_tags` table.
- **repo prior**: handled separately from tags using existing `engram_repo_stats` (per-repo match counts) plus `prerequisites.repos` for hard gating. Not a tag.
- **environment detection**: used only as extraction-time hints passed to the LLM, not stored as ranking features.

The key rule: if `react` matters because the engram is about React, store `react` as a content tag. If `react` is only present because the repo happened to use React, don't store it at all.

Scoring becomes:

```
final_score = w_semantic * semantic_score
            + w_content  * content_tag_affinity    # prompt-derived tags vs engram content tags
            + w_repo     * repo_prior              # from engram_repo_stats match counts
            + w_feedback * feedback_prior           # from engram_tag_relevance eval signal
```

No separate environment-tag scorer. Each feature does one job.

## Solution

### 1. Schema: `engram_tags` table (content tags only)

```sql
CREATE TABLE engram_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engram_id INTEGER NOT NULL REFERENCES engrams(id),
    tag TEXT NOT NULL,
    confidence REAL DEFAULT NULL,
    source TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(engram_id, tag)
);
CREATE INDEX idx_engram_tags_engram ON engram_tags(engram_id);
CREATE INDEX idx_engram_tags_tag ON engram_tags(tag);
```

No `kind` column — there's only one kind now: content/topic tags. Simpler schema, simpler queries.

- `confidence`: optional LLM confidence or similarity score when tag was assigned
- `source`: how the tag was created — `'extraction-llm'`, `'dedup-llm'`, `'backfill'`, `'manual'`
- `UNIQUE(engram_id, tag)`: one tag per engram

### 2. Pipeline-by-pipeline migration

Remove `prerequisites.tags` entirely. The `prerequisites` JSON retains only hard constraint fields: `repos`, `paths`, `os`, `mcp_servers`. Every pipeline stage that touches tags must be updated.

#### 2a. Search scoring (`src/search/engine.py`)

| Current | Change |
|---|---|
| `engine.py:142-174` — tag affinity embeds `prerequisites.tags`, cosine sim vs env tag embedding | **Replace**: content tag affinity from `engram_tags` (task #020). Initially 0.0 until backfill populates content tags. |
| `engine.py:195-217` — repo tag adjustment reads `repo:*` from `prerequisites.tags` | **Replace**: repo prior from `engram_repo_stats.times_matched` (see section 5) |
| `engine.py:219-237` — tag relevance filter/boost calls `get_tag_relevance_with_evidence(engram_id, env_tags)` | **Rekey to prompt-derived content tags**: after migration, `engram_tag_relevance` rows are keyed by content tags. The feedback prior in search must be keyed by the **current prompt-derived content tags** (from step 2 of task #020), not by the engram's own stored tags. This answers "has this engram been useful when *this topic* was active?" — a contextual signal, not a generic popularity prior. If no prompt-derived tags are available (e.g. empty query), fall back to overall average across all the engram's content tag relevance scores. Neutral scores until content tag relevance data accumulates. |
| `engine.py:260-266` — `_engram_has_all_tags()` checks required tags in prerequisites | **Rewrite**: if search `tags` filter is kept, check against `engram_tags` table instead of `prerequisites.tags` |

#### 2b. Environment / prerequisites (`src/search/environment.py`)

| Current | Change |
|---|---|
| `environment.py:199-207` — `check_prerequisites` checks tags as subset of env | **Remove**: tags no longer in prerequisites |
| `environment.py:103-132` — `check_tag_prerequisites()` | **Remove entirely** |
| `environment.py:11-32` — `detect_environment()` returns `tags` in env dict | **Keep**: env detection still runs, tags passed to extraction LLM as context. Not stored or scored. |

#### 2c. Extraction (`src/pipeline/extractor.py`)

| Current | Change |
|---|---|
| `extractor.py:580` — reads `relevant_tags` from LLM output | **Rename** to `env_relevant_tags`, extraction context only |
| `extractor.py:588-596` — merges `relevant_tags` into `prerequisites.tags`, falls back to `_enrich_with_session_tags` | **Remove fallback**, do not write tags to prerequisites. Write content tags to `engram_tags` instead. |
| `extractor.py:599` — `tags_to_score` falls back to `env_tags` | **Remove**: no env tag scoring path |
| `extractor.py:606-607, 620-621` — `update_tag_relevance(engram_id, {tag: 0.5}, weight=1.0)` keyed by env tags | **Rekey**: score content tags (from new `content_tags` output field), not env tags |
| `extractor.py:182-204` — `_enrich_with_session_tags()` | **Remove entirely** |
| `extractor.py:524` — passes `env_tags` to Claude extraction prompt | **Keep**: env tags remain useful as extraction context |

#### 2d. Evaluation (`src/pipeline/evaluator.py`)

| Current | Change |
|---|---|
| `evaluator.py:232` — loads `env_tags` from `session_audit` | **Change**: load content tags from `engram_tags` for evaluated engrams. Env tags from `session_audit` still passed to LLM as context. |
| `evaluator.py:261-274` — sends env_tags + engrams to Claude, gets `tag_scores` keyed by env tags | **Rekey**: LLM evaluates content tags. Pass each engram's content tags from `engram_tags`. LLM returns scores keyed by content tags. |
| `evaluator.py:288` — `update_tag_relevance(engram_id, tag_scores, weight=1.0)` | **Keep** the call, but scores now keyed by content tags |

#### 2e. Auto-pin system (`src/core/db.py`)

| Current | Change |
|---|---|
| `db.py:281-356` — `find_auto_pin_tag_subsets()` finds minimal env tag subsets from `engram_tag_stats` above AUTO_PIN_THRESHOLD (15) | **Rethink**: pin decisions based on (1) repo match count from `engram_repo_stats` — pin if consistently useful in specific repos, (2) content tag relevance from `engram_tag_relevance` — pin if high positive scores with enough evidence. No tag-subset prerequisites. |
| `db.py:359-453` — `update_match_stats()` increments `engram_tag_stats` per tag-set, calls `find_auto_pin_tag_subsets()` | **Simplify**: stop writing to `engram_tag_stats` for env tag sets. Match stats already flow to `engram_repo_stats`. Auto-pin trigger moves to repo threshold + content tag relevance evidence. |
| `db.py:867-941` — `check_and_apply_pin_decisions()` auto-pins at avg tag relevance > 0.6, unpins at < 0.2, writes `prerequisites.tags = positive_tags` | **Rewrite**: pin/unpin based on content tag relevance + repo stats. Pinned engrams get `prerequisites.repos` (if repo-specific) but no `prerequisites.tags`. Thresholds may need recalibration for content tag score distributions. |
| `engram_tag_stats` table | **Deprecate**: no longer written after migration. Keep read-only for historical analysis or drop. |

#### 2f. Hooks

| Current | Change |
|---|---|
| `hooks/on_session_start.py:65-72` — calls `check_structural_prerequisites()` + `check_tag_prerequisites()` + `get_tag_relevance_with_evidence()` | **Remove** `check_tag_prerequisites()`. Keep structural check. **Session-start has no prompt** — there are no prompt-derived content tags to key against. The soft-gate for pinned injection at session start must use **repo prior only** (from `engram_repo_stats` for current repo) plus an overall content-tag-agnostic feedback score (average across all the engram's content tags in `engram_tag_relevance`, not keyed to a specific context). This is a generic "is this engram generally useful?" check, not a context-specific one. Prompt-specific content tag scoring only applies in prompt/tool hooks where a query exists. |
| `hooks/on_prompt.py` — calls `search(enforce_prerequisites=True)` | **No change** — goes through engine.py |
| `hooks/on_tool_use.py` — calls `search_for_tool_context()` | **No change** |
| `hooks/on_post_tool.py` — calls `search()` | **No change** |

#### 2g. Daemon (`src/infra/daemon.py`)

| Current | Change |
|---|---|
| `daemon.py:149-152` — pinned retrieval calls `check_tag_prerequisites()` | **Remove**: only `check_structural_prerequisites()` remains |
| `daemon.py:153-156` — `get_tag_relevance_with_evidence()` soft-gate | **Change**: pinned retrieval has no prompt context. Use overall average across all engram's content tags in `engram_tag_relevance` as generic usefulness check + repo prior. Same approach as session-start hook (section 2f). |

#### 2h. MCP tools (`src/infra/mcp_server.py`)

| Current | Change |
|---|---|
| `mcp_server.py:91-167` — `engrammar_add()` takes `tags` param, merges into `prerequisites.tags` | **Rewrite**: `tags` param writes to `engram_tags` with `source='manual'` |
| `mcp_server.py:60-87` — `engrammar_search()` has `tags` filter | **Rewrite**: filter against `engram_tags` table |
| `mcp_server.py:201-300` — `engrammar_feedback()` derives tag scores from env tags, calls `update_tag_relevance()` | **Rekey**: derive scores from engram's content tags (from `engram_tags`), not env tags. Explicit `tag_scores` param keys should be content tags. |

#### 2i. CLI (`cli.py`)

| Current | Change |
|---|---|
| `cli.py:129-163` — `cmd_add()` with `--tags` → `prerequisites.tags` | **Rewrite**: `--tags` writes to `engram_tags` with `source='manual'` |
| `cli.py:95-126` — `cmd_search()` with `--tags` filter | **Rewrite**: filter against `engram_tags` table |
| `cli.py:44-92` — `cmd_status()` shows tag index | **Update**: show `engram_tags` stats instead of old tag index |
| `cli.py:13-41` — `cmd_setup()` builds `build_tag_index()` | **Update**: build content tag vocab index from `engram_tags` |

#### 2j. Embeddings (`src/core/embeddings.py`) and all `build_tag_index()` callers

| Current | Change |
|---|---|
| `embeddings.py:64-104` — `build_tag_index()` embeds `prerequisites.tags` per engram | **Drop**: replaced by content tag vocab index in task #020 |
| `embeddings.py:107-125` — `load_tag_index()` | **Drop**: replaced by content tag vocab index |

All callers of `build_tag_index()` must be updated to build the content tag vocab index instead:

| Caller | Location |
|---|---|
| Extraction post-processing | `extractor.py:703`, `extractor.py:816`, `extractor.py:1059`, `extractor.py:1347` |
| CLI setup | `cli.py:36` (`cmd_setup`) |
| CLI rebuild | `cli.py:264` |
| CLI import | `cli.py:177` |
| CLI update | `cli.py:533` |
| CLI reextract | `cli.py:775` |
| Dedup post-merge | `dedup.py:506` |

#### 2k. Deduplication (`src/pipeline/dedup.py`)

| Current | Change |
|---|---|
| `dedup.py:506` — rebuilds `build_tag_index()` after merges | **Update**: rebuild content tag vocab index |
| `db.py:1307-1316` — `prerequisites.tags` union during merge | **Remove**: no tags in prerequisites. Content tags merged via `engram_tags` (re-point absorbed rows to survivor, dedup on conflict). LLM-refined content tags later (section 7). |

#### 2l. Session audit (`src/core/db.py`)

| Current | Change |
|---|---|
| `db.py:664-674` — `write_session_audit()` stores `env_tags` JSON | **Keep**: `session_audit.env_tags` useful as context for evaluation LLM and provenance/debugging. Not used for scoring. |
| `db.py:677-707` — `get_env_tags_for_sessions()` | **Keep**: evaluation reads this for LLM context |

#### 2m. Existing relevance data (`engram_tag_relevance`)

Existing rows are keyed by env tags (e.g. `react`, `typescript`, `repo:engrammar`). After migration:
- **Reset**: truncate `engram_tag_relevance` during backfill. Old env-tag-keyed scores are meaningless for content tags.
- New relevance data accumulates naturally as extraction and evaluation produce content-tag-keyed scores.
- Table schema unchanged — only the key semantics change.

**Rollout order:**

1. Create `engram_tags` table
2. Update write-side: extraction emits content tags to `engram_tags`, MCP/CLI `--tags` writes to `engram_tags`
3. Update read-side: search scoring, tag relevance filter, MCP search filter, CLI search filter — all read from `engram_tags`
4. Rewrite auto-pin to use repo stats + content tag relevance (no tag-subset prerequisites)
5. Remove `check_tag_prerequisites()` from hooks, daemon, environment.py
6. Replace repo tag adjustment with `engram_repo_stats` repo prior
7. Run backfill: generate content tags, reset `engram_tag_relevance`, clean `prerequisites.tags`
8. Drop old `build_tag_index`, deprecate `engram_tag_stats`

### 3. Fix `relevant_tags=[]` semantics and rename to `env_relevant_tags`

Rename `relevant_tags` to `env_relevant_tags` in the extraction output schema. This field is "subset of detected environment tags the LLM considers relevant" — used only as extraction-time context, not stored as ranking features.

In `src/pipeline/extractor.py:588-596`:
- When LLM returns `env_relevant_tags=[]`, empty must remain empty — do NOT fall back to full env tags via `_enrich_with_session_tags`
- The extraction prompt already allows empty tags for generic engrams; the code must respect that

In `src/pipeline/extractor.py:599`:
- `tags_to_score` should be `[]` when `env_relevant_tags` is empty, not fall back to `env_tags`

Since environment tags are no longer stored as ranking features, the `_enrich_with_session_tags` function and the tag-scoring path for env tags can be removed entirely after migration.

### 4. Extract content tags during extraction

Have the extraction LLM emit 1-3 short topic labels per engram. Add a `content_tags` field to the extraction output schema. Environment tags are passed to the LLM as context (so it understands the project), but only content tags are stored.

Canonicalize after extraction: lowercase, deduplicate, strip whitespace. Insert into `engram_tags` with appropriate `source`.

**MVP**: LLM generates content tags directly from engram text.

**Later enhancement** (after task #020 builds tag vocab index): vector similarity proposes candidate tags from vocabulary, LLM validates/refines.

Examples:
- "The priority profile creation form has cascading field dependencies" → `["forms", "cascading-fields"]`
- "Always use `screen.getByRole` over `getByTestId` in React Testing Library" → `["testing", "react", "rtl"]`
- "Jira API tokens can be invalidated server-side" → `["jira", "authentication"]`

### 5. Repo prior from `engram_repo_stats`

Replace the current `repo:*` tag matching (`engine.py:195-217`) with a proper repo prior:

- Use `engram_repo_stats.times_matched` for the current repo as a soft signal
- Current repo from `env["repo"]`, engram's repo history from `engram_repo_stats`
- If the engram has positive matches in the current repo, apply a small boost
- If the engram has matches only in other repos, apply a small penalty (but don't hard-filter — cross-repo leakage is intentional)
- If the engram has positive matches across multiple repos, reduce the repo-specific prior (the engram is becoming generic)
- Config: `scoring.repo_match_boost`, `scoring.repo_mismatch_penalty` (already exist in config.json)

### 6. Backfill existing corpus (required)

- **Generate content tags**: for each active engram, extract content tags from its text (LLM pass over batches). Insert into `engram_tags` with `source='backfill'`.
- **Do NOT migrate env tags**: old `prerequisites.tags` values like `typescript`, `monorepo`, `frontend` are not content tags — they're environment noise. They get dropped, not migrated. If any are genuinely topical (e.g. `react` on a React-specific engram), the backfill LLM will independently produce them as content tags.
- **Clean prerequisites**: remove `tags` key from `prerequisites` JSON for all engrams.

### 7. Refine content tags during deduplication (later)

Piggyback on the existing dedup LLM call. Add a `content_tags` field to the dedup group response:

```json
{
  "ids": [52, 63],
  "canonical_text": "Don't add migration code for dev-only projects.",
  "content_tags": ["dev-workflow", "migrations"],
  "confidence": 0.93,
  "reason": "Same rule, different wording."
}
```

### 8. Use content tags in search (via task #020)

Task #020 builds a tag vocabulary index from `engram_tags` and implements prompt→content tag matching. See task #020 for details.

## Sequence

1. **This issue (#039)**: `engram_tags` table + remove env tag scoring + repo prior + fix extraction semantics + MVP content tag extraction + backfill
2. **Task #020**: prompt-derived content tag affinity + tag vocab index
3. **Later**: dedup refinement of content tags (section 7)
4. **Last, if still needed**: feedback-driven tag cleanup (soft suppression, not destructive pruning)

## Files

- `src/core/db.py` — `engram_tags` table, migration, query helpers, remove `tags` from prerequisites, rewrite auto-pin (no tag-subset prereqs), deprecate `engram_tag_stats`
- `src/pipeline/extractor.py` — fix `relevant_tags=[]` fallback, rename to `env_relevant_tags`, emit content tags to `engram_tags`, rekey `update_tag_relevance` to content tags, remove `_enrich_with_session_tags`
- `src/pipeline/evaluator.py` — load content tags from `engram_tags` for evaluation, rekey LLM `tag_scores` to content tags
- `src/pipeline/dedup.py` — remove env tag union from merge, merge content tags via `engram_tags` table, update index rebuild
- `src/search/engine.py` — replace env tag affinity with content tag scoring, replace `repo:*` matching with repo prior, rekey tag relevance filter/boost, rewrite `_engram_has_all_tags`
- `src/search/environment.py` — remove `check_tag_prerequisites`, remove tag check from `check_prerequisites`
- `src/core/embeddings.py` — drop `build_tag_index` / `load_tag_index` (replaced by content tag vocab index in task #020)
- `src/infra/daemon.py` — remove `check_tag_prerequisites()`, rekey `get_tag_relevance_with_evidence()`
- `src/infra/mcp_server.py` — `engrammar_add` tags → `engram_tags`, `engrammar_search` filter → `engram_tags`, `engrammar_feedback` rekey to content tags
- `hooks/on_session_start.py` — remove `check_tag_prerequisites()` call
- `cli.py` — `--tags` writes to `engram_tags`, search filter reads `engram_tags`, backfill command, status shows content tag stats
- `prompts/extraction/transcript.md` — add `content_tags` field, rename `relevant_tags` → `env_relevant_tags`

## Notes

- Hard constraints (repos, paths, os, mcp_servers) remain in `prerequisites` JSON — unchanged
- Environment detection remains useful — passed to extraction LLM as context, not stored
- Cross-repo leakage is preserved: strong semantic match surfaces engrams even without repo match
- Feedback-driven tag pruning is deferred — safer as soft suppression first
- Cold start: when no content tags exist yet, extraction generates them from text alone. These bootstrap the vocabulary for future prompt-derived matching.
- `engram_tag_relevance` table continues to track per-tag evaluation signal — but tags now refer to content tags, not env tags. Existing relevance data for env tags becomes stale and should be archived or reset during backfill.
