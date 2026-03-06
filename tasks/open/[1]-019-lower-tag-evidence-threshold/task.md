# Task: Lower tag relevance evidence threshold

- Priority: High
- Complexity: C1
- Status: Open

## Problem

The tag relevance filter in both `hooks/on_session_start.py:62` and `src/search/engine.py:167` requires **3+ evaluations** before filtering out negatively-scored engrams. This means new or rarely-evaluated engrams pass through freely and generate noise for multiple sessions before the system learns to suppress them.

Combined with the conservative threshold of `avg_score < -0.1`, the system is very slow to learn from negative feedback.

## Fix

1. Lower `MIN_EVALS_FOR_FILTER` from 3 to 2 in `src/search/engine.py`
2. Lower the equivalent threshold in `hooks/on_session_start.py` (line 62: `total_evals >= 3`)
3. Consider also relaxing the score threshold from `-0.1` to `-0.05` so weaker negative signals still filter

## Files

- `src/search/engine.py` — `MIN_EVALS_FOR_FILTER` constant (line 167)
- `hooks/on_session_start.py` — pinned engram tag relevance check (line 62)

## Validation

- Give negative feedback on an engram twice and verify it stops appearing in the next session
- Confirm that engrams with mixed feedback (1 positive, 1 negative) are NOT filtered (avg ~0, above threshold)
