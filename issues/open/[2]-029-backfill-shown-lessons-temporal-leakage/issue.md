# Issue #29: Shown-Engram Backfill Uses Present-Day Engram Set

- Severity: High
- Complexity: C2 (Medium complexity)
- Status: Open

## Problem
`_backfill_shown_engrams()` reconstructs historical `shown_engram_ids` by searching user prompts against the current engram database, not the engram set that existed when the session happened.

## Why It Matters
Session audit becomes temporally incorrect: sessions can be marked as having shown engrams that were created later. This pollutes evaluator inputs and can skew tag relevance scores.

## Suggested High-Level Solution
1. Snapshot or filter candidate engrams by `created_at <= session timestamp`.
2. Keep backfill logic bounded to engrams that were actually eligible at that time.
3. Add a regression test proving a post-session engram is never backfilled into older sessions.
4. Consider storing explicit "backfilled_by_version" metadata for traceability.
