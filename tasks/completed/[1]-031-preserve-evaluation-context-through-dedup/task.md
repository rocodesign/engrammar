# Task: Preserve Evaluation Context Through Dedup Merges

- Priority: High
- Complexity: C1
- Status: Done (2026-03-26)

## Update (2026-03-26): Fixed

Both merge bugs are now fixed in `merge_engram_group()`:

1. **session_shown_engrams** — Changed from `INSERT OR IGNORE` (4 columns) to upsert with all 6 columns. Uses `COALESCE` on conflict to keep existing survivor context and backfill NULLs from the absorbed row.

2. **session_audit.engram_context** — Merge now rewrites JSON keys from absorbed IDs to survivor ID, with field-level backfill (prompt_tags, query_text, hook_event).

Tests added: `test_merge_preserves_shown_engram_prompt_context`, `test_merge_backfills_shown_context_without_overwriting`, `test_merge_rewrites_session_audit_engram_context`.

Production DB audit at fix time: 6 orphaned engram_context keys across 3 sessions, 259 shown-engram rows pointing to deprecated engrams. Future merges will preserve context correctly.

## Update (2026-03-25): Partially implemented

The new evaluation context this task is trying to protect now exists:

- `session_shown_engrams.prompt_tags`
- `session_shown_engrams.query_text`
- `session_audit.engram_context`

The remaining bug is in the dedup merge path itself:

- merge still rewrites `session_shown_engrams` using the old column set
- merge rewrites `session_audit.shown_engram_ids` but not `session_audit.engram_context`

So the prerequisite work landed, but the actual preservation fix is still open.

## Problem

The recent evaluation improvements store prompt-derived context on shown engrams:

- `session_shown_engrams.prompt_tags`
- `session_shown_engrams.query_text`
- `session_audit.engram_context`

This context is now required for:

- weighted content-tag attribution during evaluation
- local transcript window extraction around the trigger turn
- later reevaluation of historical sessions

The dedup merge path still rewrites `session_shown_engrams` using the old column set:

```python
INSERT OR IGNORE INTO session_shown_engrams (session_id, engram_id, hook_event, shown_at)
SELECT session_id, ?, hook_event, shown_at
FROM session_shown_engrams WHERE engram_id = ?
```

That silently drops `prompt_tags` and `query_text` when an absorbed engram is rewritten to the survivor. The same merge path also rewrites `session_audit.shown_engram_ids` but does not rewrite `session_audit.engram_context`, leaving context keyed by absorbed IDs.

As a result, any evaluation or reevaluation that runs after dedup can lose the context needed to score the survivor correctly.

## Required fix

### 1. Preserve shown-engram context on merge

When rewriting `session_shown_engrams`, copy the new context columns too:

- `prompt_tags`
- `query_text`

Use an upsert rather than `INSERT OR IGNORE` so that if both survivor and absorbed rows exist for the same `(session_id, engram_id)`, the merge preserves existing survivor context and backfills missing values from the absorbed row instead of dropping them.

### 2. Rewrite `session_audit.engram_context`

When `shown_engram_ids` are rewritten from absorbed IDs to the survivor ID, the same merge must also rewrite `engram_context` keys:

- move absorbed-ID entries onto the survivor ID
- preserve survivor context if it already exists
- backfill missing `prompt_tags`, `query_text`, and `hook_event` from absorbed entries

### 3. Keep historical reevaluation safe

The fix should work for:

- immediate same-session evaluation
- delayed evaluation if dedup runs first
- reevaluation of older sessions after later dedup passes

## Tests

Add coverage for:

1. merging a shown engram preserves `prompt_tags` and `query_text`
2. merging into an existing survivor row backfills missing shown context instead of nulling it out
3. merging rewrites `session_audit.engram_context` from absorbed ID to survivor ID

## Why high priority

This is a regression in the new evaluation pipeline. It does not just lose optional metadata; it breaks the evidence needed by the new scoring logic and makes later evaluation results less trustworthy.

## MetaClaw-inspired: Provenance exclusion (MAML-style support/query separation)

MetaClaw enforces a clean separation between "support" samples (sessions that triggered a skill evolution) and "query" samples (sessions that test the new skill). The engrammar analogue:

- Sessions that **created** an engram (via extraction) should not be the primary evidence used to evaluate that engram's general usefulness
- Sessions that **triggered a dedup merge** should not evaluate the survivor using pre-merge context
- Promotion decisions (#012) should lean more on **later reuse** than on the originating session

### Proposed addition

When merging evaluation context, add a `provenance` flag to distinguish:

```python
# In session_shown_engrams or session_audit:
provenance = "source"   # this session created/triggered the engram
provenance = "reuse"    # this session received the engram via normal search
```

The evaluator can then weight "reuse" evidence higher than "source" evidence when computing tag relevance, or exclude "source" sessions entirely from EMA updates.

This prevents the circular pattern where an engram extracted from session A is shown in session A's audit, evaluated against session A's transcript, and gets a positive score simply because it matches its own origin context.

### Relation to new tasks

- `#039` (failure-driven evolution) — rewrite sessions are "source", later sessions are "query"
- `#040` (engram versioning) — version boundary is a natural provenance boundary

## Files

- `src/core/db.py`
- `tests/test_database.py`
