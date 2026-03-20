# Task: LLM-Assisted Engram Deduplication

- Priority: Medium
- Complexity: C3
- Absorbs: #004 (LLM-assisted engram merge)
- Status: Open

## Problem

The current inline dedup (`find_similar_engram` at 0.85 embedding / 0.70 word-overlap) only catches near-identical text. Conceptual duplicates - same lesson expressed differently across sessions - slip through. Current DB has 3 major duplicate clusters (14 engrams that should be ~3):

- **5 engrams** (#52, #53, #55, #58, #63): "no migration/compat code for dev-only projects"
- **6 engrams** (#54, #56, #57, #59, #60, #65): "update DB content when renaming terminology"
- **3 engrams** (#71, #72, #73): "update docs after code changes"

### Success criteria

- Collapse the known 14-engrams duplicate set into 3-4 canonical engrams.
- No false merges on curated negative fixtures (distinct engrams that are semantically close but not duplicates).
- Idempotent behavior: running dedup repeatedly after convergence causes no further DB changes.

## Scope

This task covers the dedup logic only - no daemon integration. The goal is a working, testable dedup function and CLI command.

### Non-goals

- No daemon scheduling changes (covered by #015).
- No manual review UI beyond CLI scan output.
- No evaluator pipeline redesign.
- No broad category taxonomy refactor.

## Design

### 1. `dedup_verified` column

Add dedup processing state on `engrams`:

- `dedup_verified INTEGER DEFAULT 0` (boolean-style pending/verified flag)
- `dedup_attempts INTEGER DEFAULT 0`
- `dedup_last_error TEXT DEFAULT NULL`

Rules:

- New engrams from extraction or `engrammar_add` start as `dedup_verified = 0`.
- Dedup worker pulls only active (`deprecated = 0`) and unverified (`dedup_verified = 0`) rows.
- If engram is processed and no merge is needed, mark `dedup_verified = 1`.
- On LLM/parse failure, increment attempts, set `dedup_last_error`, keep `dedup_verified = 0` (retryable).
- Ensure query performance with index on `(deprecated, dedup_verified, id)`.

### 2. LLM-assisted dedup logic (batched pairs against verified pool)

Process unverified engrams by pairing each with its verified candidates, then batch multiple pairs into one Haiku call:

1. Gather all engrams where `dedup_verified = 0`.
2. For each unverified engram, find candidates: **only verified** engrams with embedding similarity >= 0.50. Exclude other unverified engrams from candidates.
3. Limit candidates per unverified engram (for example `top_k <= 8`) to cap prompt growth.
4. Bundle multiple unverified+candidates pairs into one Haiku call by a token/character budget (not only item count). Shared verified candidates across pairs give Haiku cross-pair visibility for global reasoning.
5. Haiku returns groupings - it can see that a verified engram appearing in multiple pairs connects them, and decide whether to merge all into one group or split into separate merges.
6. Validate returned groups strictly before mutation (IDs exist, are unique, belong to the input batch, group size >= 2, no deprecated rows).
7. For each valid group: merge in one DB transaction.
8. Unverified engrams with no match: mark `dedup_verified = 1`.

**Why unverified vs verified only**: Clustering unverified engrams together can destroy bridge connections. If A(ver) and B(ver) don't match each other, but unverified D matches B while unverified C matches A - clustering {C, A, D} would absorb D into A, eliminating the bridge to B. By only pairing unverified against verified, each unverified engram finds its own match independently. D survives to find B because C can't consume D first.

**Why batch multiple pairs**: Sending pairs independently could produce contradictory decisions. If E(unver) has candidates {A(ver), B(ver)} and G(unver) has candidates {B(ver)}, Haiku sees B in both groups and can make a global call - either merge E+A+B+G all together, or split into E+A and G+B. One call instead of N, with better decisions.

### 3. LLM response contract

Require strict JSON response shape from Haiku, for example:

```json
{
  "groups": [
    {
      "ids": [52, 53, 55],
      "canonical_text": "No migration or compatibility code is needed for dev-only projects.",
      "confidence": 0.93,
      "reason": "Same rule, phrased differently."
    }
  ],
  "no_match_ids": [71]
}
```

If parsing/validation fails, fail the batch safely (no partial mutation), record error, and leave rows retryable.

### 3.1 Draft merge prompt (implementation-ready)

Use a two-part prompt: fixed system instruction + structured user payload.

System prompt draft (common core):

```text
You are deduplicating "engrams" — short actionable lessons extracted from coding sessions.

Your job:
1) Identify true duplicate groups.
2) Propose one canonical text per duplicate group.
3) Report unmatched IDs according to mode-specific accounting rules.

High precision is required. If uncertain, do NOT merge.

Merge only when ALL are true:
- Same core action/recommendation
- Same trigger/context constraints
- Same expected outcome or rationale

Do NOT merge when ANY are true:
- They are topically related but prescribe different actions
- One is broader/umbrella guidance and another is a specific sub-rule
- Preconditions differ materially (repo/tool/path/os constraints differ)
- Details conflict (commands, flags, file paths, versions, APIs)

Canonical text rules:
- 1-2 sentences, concrete and actionable
- Preserve important specifics from source items (commands, flags, paths, code spans)
- Do not invent new facts not present in the input
- Keep wording concise and implementation-neutral

Output must be strict JSON matching the required schema. No markdown fences.
If uncertain, return fewer groups and place IDs in no_match_ids.
```

Mode-specific prompt snippet (`mode = incremental`):

```text
You are in INCREMENTAL mode.

Input contains:
- UNVERIFIED engrams that must be decided this pass
- VERIFIED candidate engrams that may be merge targets/bridges

Decision rules:
1) For each unverified engram, decide if it duplicates any verified candidate.
2) If a verified candidate bridges multiple unverified engrams, you may form one multi-ID group.
3) Every unverified ID must appear exactly once: either in one group or in no_match_ids.
4) Verified-only IDs must not appear in no_match_ids.
5) Every group must include at least one unverified ID.
```

Mode-specific prompt snippet (`mode = bootstrap`):

```text
You are in BOOTSTRAP mode.

Input may contain only unverified engrams (or mostly unverified).
There is no stable verified pool yet.

Decision rules:
1) Use candidate_edges to reason globally and form duplicate groups.
2) Every input ID must appear exactly once: either in one group or in no_match_ids.
3) Groups may be formed from any IDs in the batch (no verified/unverified restriction).
```

User payload template (formatted JSON string in prompt):

```json
{
  "mode": "incremental",
  "batch_id": "run-2026-02-27T12:00:00Z-pass2-batch4",
  "rules": {
    "min_confidence_hint": 0.8,
    "max_groups": 20
  },
  "engrams": [
    {
      "id": 52,
      "status": "unverified",
      "text": "Do not add migration or compatibility code for dev-only projects.",
      "category": "development/backend",
      "prerequisites": {"repos": ["engrammar"]},
      "occurrence_count": 3
    },
    {
      "id": 63,
      "status": "verified",
      "text": "Skip compat migration layers in internal-only development repos.",
      "category": "development/backend",
      "prerequisites": {"repos": ["engrammar"]},
      "occurrence_count": 5
    }
  ],
  "candidate_edges": [
    {"source_id": 52, "target_id": 63, "similarity": 0.84}
  ]
}
```

Bootstrap payload variant:

```json
{
  "mode": "bootstrap",
  "batch_id": "run-2026-02-27T12:00:00Z-bootstrap-pass1-batch1",
  "rules": {
    "min_confidence_hint": 0.8
  },
  "engrams": [
    {"id": 52, "status": "unverified", "text": "..."},
    {"id": 53, "status": "unverified", "text": "..."},
    {"id": 65, "status": "unverified", "text": "..."}
  ],
  "candidate_edges": [
    {"source_id": 52, "target_id": 53, "similarity": 0.86},
    {"source_id": 53, "target_id": 65, "similarity": 0.79}
  ]
}
```

Expected output schema (strict):

```json
{
  "groups": [
    {
      "ids": [52, 63],
      "canonical_text": "Do not add migration or compatibility code for dev-only/internal projects.",
      "confidence": 0.93,
      "reason": "Same rule and constraints; wording differs."
    }
  ],
  "no_match_ids": [],
  "notes": []
}
```

Output constraints:

- `groups[].ids` must be unique positive integers; no ID may appear in more than one group.
- Group size must be >= 2.
- `confidence` must be float in `[0,1]`.
- `reason` short (`<= 160 chars`).
- Confidence gate: emit a group only if `confidence >= min_confidence_hint`.
- In `incremental` mode, every **unverified** input ID must appear exactly once, either in a group or in `no_match_ids`.
- In `incremental` mode, each group must include at least one `unverified` ID.
- In `bootstrap` mode, every input ID must appear exactly once, either in a group or in `no_match_ids`.
- Deterministic ordering: sort each `groups[].ids` ascending.
- Deterministic ordering: sort `groups` by smallest ID in each group (ascending).
- Deterministic ordering: sort `no_match_ids` ascending.

Recommended post-parse safety checks in code:

- Reject output if any ID is unknown, duplicated, or missing.
- Reject output if canonical text is empty or exceeds sentence limit.
- Reject/trim if `notes` is unexpectedly large.
- On reject, mark batch failed and retry later (no partial merge).

### 4. Merge semantics (data safety)

For each duplicate group, choose one deterministic survivor (for example: prefer verified, then highest `occurrence_count`, then lowest ID), and absorb all others.

Minimum merge behavior:

- `engrams`: update survivor text/category/prereqs/pin fields, merge sessions, recalculate `occurrence_count`, mark survivor verified.
- `engram_categories`: union categories onto survivor.
- `engram_repo_stats`: move and aggregate per-repo counts.
- `engram_tag_stats`: move and aggregate per-tag-set counts.
- `engram_tag_relevance`: merge tag relevance rows safely (preserve evidence counts and score signal).
- `session_shown_engrams`: rewrite absorbed IDs to survivor with duplicate-safe upsert behavior.
- `session_audit.shown_engram_ids` JSON: replace absorbed IDs with survivor IDs.
- `hook_event_log.engram_ids` JSON: replace absorbed IDs with survivor IDs.
- absorbed engrams: set `deprecated = 1`, keep historical row, mark verified to avoid reprocessing.

Prerequisites and relevance merge policy:

- `prerequisites.tags`: do **not** naive-union (would over-constrain because tags are AND-gated when used as prerequisites). Prefer intersection; if intersection is empty, drop tag prerequisite and rely on tag relevance scoring.
- `prerequisites.repos` / `repo`: normalize to `repos`, then union (OR semantics in matcher).
- `prerequisites.os`: union list (OR semantics in matcher).
- `prerequisites.paths`: union path prefixes (OR semantics in matcher).
- `prerequisites.mcp_servers`: intersection (AND semantics in matcher; union would over-restrict).
- Unknown prerequisite keys: preserve survivor value unless there is a safe deterministic merge rule.
- `engram_tag_relevance`: merge by evidence-weighted average score per tag; sum positive/negative eval counters.

All group merges must be transactional.

### 5. Text refinement on merge

When merging a duplicate group, pick the best canonical text in the same call:

- Part of the cluster prompt: "For each duplicate group, return the most specific and actionable version. Combine if multiple add unique detail."
- Specificity guard: verify backtick code spans and concrete details from originals survive.
- Keep to 1-2 sentences max.
- If generated text fails validation, fallback to deterministic best-existing text heuristic (prefer concrete details, code spans, and higher specificity).

### 6. CLI commands

- `engrammar dedup` - process all unverified engrams (run dedup logic in a loop)
- `engrammar dedup --scan` - show clusters without merging (dry run for visibility)
- `engrammar dedup --limit N` - process at most N engrams
- `engrammar dedup --json` - machine-readable scan/run output
- `engrammar dedup --batch-size N` - tune pair batch sizing
- `engrammar dedup --max-candidates N` - tune per-engram candidate cap
- `engrammar dedup --min-sim F` - tune candidate embedding floor
- `engrammar dedup --id N` - inspect/process a specific engram

`--scan` output should include proposed groups, survivor choice, confidence, and rationale.

Run summary should include: processed, merged, marked verified, skipped, failed, and retryable counts.

### 7. Keep existing inline threshold check

The fast `find_similar_engram(0.85)` check at insertion time stays. It catches obvious duplicates cheaply. The dedup job catches what it misses.

Optional improvement: if inline dedup merges into an existing engram but incoming text appears richer, mark survivor as unverified so scheduled dedup can refine canonical text later.

### 8. Cold-start bootstrap mode

When dedup runs on a DB where all engrams are unverified, standard unverified-vs-verified flow is order-sensitive and weak.

Bootstrap rule:

- If verified pool is empty (or below a small threshold), run a bootstrap pass over all active engrams:
  - build candidate graph from embedding neighbors (`top_k`) with floor similarity
  - process highest-similarity candidates/components first
  - run LLM grouping on these candidates to create initial canonical survivors
- After bootstrap creates a meaningful verified pool, switch to normal unverified-vs-verified mode.

This avoids "first processed engram wins" behavior.

### 9. Merge invalidation

After a merge, the survivor's text/embedding may change enough that prior decisions are stale.

- Survivor should be re-queued for dedup (`dedup_verified = 0`) after merge.
- Reset survivor error fields (`dedup_last_error = NULL`) and keep attempts bounded to avoid runaway retries.

This ensures newly strengthened survivor text can be compared again in later passes.

### 10. Convergence / multi-pass behavior

Single pass is insufficient because merges change candidates and embeddings.

- `engrammar dedup` should run multi-pass until stable:
  - stop when a pass produces zero merges and no remaining unverified rows
  - or when `--max-passes N` is reached (safety guard)
- Rebuild/reload embedding index between passes when merges occurred.
- Provide `--single-pass` for debugging, but default should seek convergence.

## Files

- `src/db.py` - dedup columns/migration, queue queries, transactional merge helpers, linked-table rewrite helpers
- `src/dedup.py` - new module: candidate selection, batching, LLM call, schema validation, orchestration
- `cli.py` - `dedup` command
- `docs/CLI.md` - add command usage and options
- `docs/ARCHITECTURE.md` - document dedup pipeline and invariants

## Testing

Use the known duplicate clusters above as ground truth. The dedup logic should:
1. Identify all members of each cluster as duplicates.
2. Merge them into one engram per cluster with best canonical text.
3. Not false-merge genuinely distinct engrams.
4. Be idempotent across repeated runs.
5. Resume safely after partial failure (retry path).
6. Preserve integrity across linked tables and JSON ID references.

Recommended test coverage additions:

- Fake-LLM contract tests (valid JSON, malformed JSON, contradictory groups).
- Merge invariants tests for `engram_*` tables plus `session_shown_engrams`.
- JSON reference rewrite tests for `session_audit.shown_engram_ids` and `hook_event_log.engram_ids`.
- CLI `--scan` snapshot-style tests.
- Cold-start bootstrap tests (all rows initially unverified).
- Multi-pass convergence tests (requires >1 pass to fully collapse duplicates).
- Merge invalidation tests (survivor rechecked after canonical text changes).

## Rollout plan

1. Backup DB and run `engrammar dedup --scan`.
2. Run bounded batches (`--limit`) and verify merge summaries.
3. Run full dedup once confidence is high.
4. Re-run to confirm idempotency (no-op).

## Open questions

- Add minimal merge audit table now? Recommended:
  - `engram_merge_log(id, run_id, survivor_id, absorbed_ids_json, canonical_text, confidence, reason, created_at)`
  - Keeps rollback/debug context without implementing full history framework.
