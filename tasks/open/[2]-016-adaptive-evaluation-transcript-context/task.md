# Task: Adaptive Transcript Context for Evaluation

- Priority: Medium
- Complexity: C2
- Status: Open

## Problem

Evaluation quality is limited by transcript truncation:

- `run_evaluation_for_session()` reads only an excerpt, not the full session transcript
- Long sessions are reduced to head+tail slices, which can miss the middle where engrams were actually applied
- This can produce false neutral scores ("not relevant") or incorrect negative/positive judgments

The current approach is fast, but it sacrifices recall for long sessions.

## Goal

Improve evaluator accuracy by giving it more complete and relevant transcript context while keeping background evaluation reasonably fast.

## Design

### 1. Adaptive transcript selection (size-based policy)

Replace the fixed excerpt strategy with a policy:

1. **Small transcript** (under threshold): send full transcript
2. **Medium transcript**: send larger transcript slice(s), not just a tiny excerpt
3. **Large transcript**: build targeted context windows and only fall back to head+tail when needed

Thresholds should be configurable/tunable after initial rollout.

### 2. Prefer evidence-rich windows over generic head+tail

For large transcripts, construct transcript context from the most useful regions:

- windows around messages likely to contain action/execution (tool usage, command output, follow-up user corrections)
- windows matching engram-specific keywords / commands / identifiers (best-effort token matching)
- optional head/tail slices as a safety net, not the primary strategy

The evaluator should see the parts most likely to answer: "was this advice acted on?"

### 3. Fallback behavior stays fail-open

If targeted window extraction fails:

- fall back to current excerpt behavior
- do not block evaluation pipeline progress

This should improve quality without making evaluation brittle.

### 4. Observability for tuning

Log enough metadata to tune the policy:

- transcript size
- strategy used (`full`, `windowed`, `head_tail_fallback`)
- final chars/tokens sent to evaluator

This complements `#014` (extraction observability) but is scoped to evaluation context selection.

## Non-goals

- Recombining extraction and evaluation into one LLM call
- Full-transcript extraction reconciliation (separate concern / future task)
- Changing evaluator scoring rubric

## Suggested implementation order

1. Add size-based `full` vs `excerpt` policy (send full transcript for small sessions)
2. Implement targeted window selection for large sessions
3. Add strategy logging and tests with long-transcript fixtures
4. Tune thresholds based on real sessions

## Files

- `src/evaluator.py` — transcript selection/windowing policy, logging
- `tests/test_evaluator.py` (or new tests) — transcript context selection behavior

