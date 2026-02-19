# Issue #29: Shown-Lesson Backfill Uses Present-Day Lesson Set

- Severity: High
- Complexity: C2 (Medium complexity)
- Status: Open

## Problem
`_backfill_shown_lessons()` reconstructs historical `shown_lesson_ids` by searching user prompts against the current lesson database, not the lesson set that existed when the session happened.

## Why It Matters
Session audit becomes temporally incorrect: sessions can be marked as having shown lessons that were created later. This pollutes evaluator inputs and can skew tag relevance scores.

## Suggested High-Level Solution
1. Snapshot or filter candidate lessons by `created_at <= session timestamp`.
2. Keep backfill logic bounded to lessons that were actually eligible at that time.
3. Add a regression test proving a post-session lesson is never backfilled into older sessions.
4. Consider storing explicit "backfilled_by_version" metadata for traceability.
