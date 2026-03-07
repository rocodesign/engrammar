# Task: Add minimum score threshold for prompt search

- Priority: High
- Complexity: C1
- Status: Open

## Problem

The UserPromptSubmit hook runs hybrid search and returns top-k results **regardless of relevance score**. Unlike the PreToolUse path which has `min_score_tool: 0.03` (`src/search/engine.py:396-398`), prompt search always injects the top 3 matches even when they're barely related to the user's prompt.

This is the single biggest source of noise — in a real session, 0/19 injected engrams were useful because the system always fills its quota rather than staying silent when nothing relevant exists.

## Fix

1. Add `min_score_prompt` config option (default ~0.02) in `src/core/config.py` alongside `min_score_tool`
2. Apply the threshold in `search()` or in `hooks/on_prompt.py` before injection — filter out results below the floor
3. Consider also applying this in the daemon's search handler for consistency

## Files

- `src/core/config.py` — add `min_score_prompt` default
- `src/search/engine.py` — apply threshold (or expose it for callers)
- `hooks/on_prompt.py` — filter results before injection
- `src/infra/daemon.py` — daemon search handler consistency

## Validation

- Run a session in an unrelated project (e.g. a frontend React app) and verify that generic/engrammar-specific engrams no longer get injected
- Compare injection counts before/after across a few sessions
