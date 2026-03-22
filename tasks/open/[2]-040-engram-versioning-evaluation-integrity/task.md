# Task: Engram Versioning for Evaluation Integrity

- Priority: Medium
- Complexity: C2
- Status: Open
- Inspired by: MetaClaw `skill_generation` counter — discards stale pre-evolution samples after skill library changes

## Problem

When an engram is materially rewritten (text change, dedup merge, or failure-driven evolution), its evaluation evidence continues to accumulate as if the engram hasn't changed. Pre-rewrite evaluations may not reflect the new text's relevance, polluting tag relevance scores with stale signal.

Example: An engram about "always use absolute imports" gets rewritten to "use absolute imports from the package root — the bundler doesn't resolve ../ paths." The old evaluations (which may have been mixed because the original was too vague) still count toward the new, more precise version.

## Proposed approach

### 1. Add `version` field to engrams

```sql
ALTER TABLE engrams ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
```

Bump on:
- Material text changes (not typo fixes — use edit distance threshold)
- Dedup merge (survivor gets version bump)
- Failure-driven rewrite (#039)

### 2. Tag evaluation evidence with version

```sql
ALTER TABLE engram_tag_relevance ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
-- Or: store per-version scores separately
```

When version bumps:
- Archive old tag relevance scores (don't delete — useful for analysis)
- Reset EMA to neutral for the new version
- New evaluations accumulate against the new version only

### 3. Attribute shown_engrams to version

Store the version that was actually shown in `session_shown_engrams`:

```sql
ALTER TABLE session_shown_engrams ADD COLUMN engram_version INTEGER;
```

Evaluator uses this to only update scores for the current version.

### 4. Evidence decay for old versions

Old-version evidence doesn't count toward current relevance. This prevents:
- Stale positive scores keeping a degraded engram in rotation
- Stale negative scores suppressing an improved engram

## Relation to existing work

- `#031` (preserve eval context through dedup) — dedup merges should bump version
- `#039` (failure-driven evolution) — rewrites should bump version
- `#030` (weighted tag attribution) — attribution applies to current version only
- `tasks/ideas/metaclaw-inspired-skill-lifecycle.md` §3 — this task implements that idea

## Files

- `src/core/db.py` — schema migration, version bump logic
- `src/pipeline/evaluator.py` — version-aware score updates
- `src/pipeline/dedup.py` — bump version on merge
- `hooks/on_stop.py` — record version in session audit
- `src/search/engine.py` — use current-version scores only
