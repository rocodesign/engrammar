# Task: Widen tag affinity penalty range

- Priority: High
- Complexity: C1
- Status: Open

## Problem

The tag affinity boost in `src/search/engine.py:129-133` applies a multiplier range of **0.5x–1.3x**. An unrelated-stack engram (e.g. engrammar-specific engram in a React project, cosine sim ~0.65) only gets halved. If it has a decent BM25/vector base score from generic terms like "refactor" or "rename", it still ranks high enough to be injected.

The penalty needs to be more aggressive so that cross-domain engrams are effectively suppressed.

## Fix

1. Change `max(0.5, ...)` to `max(0.2, ...)` in the tag affinity multiplier calculation
2. This gives a 5x harsher penalty for unrelated stacks while keeping the 1.3x boost for matching stacks
3. Consider also adjusting the similarity breakpoints — currently mapped linearly from 0.65→0.5x to 0.95→1.3x

## Files

- `src/search/engine.py` — tag affinity boost calculation (line ~133, both vectorized and fallback paths)

## Validation

- Search for a frontend-specific engram from within the engrammar repo (Python project) and verify the score is significantly lower than before
- Search for a Python-specific engram from within a React project and verify suppression
