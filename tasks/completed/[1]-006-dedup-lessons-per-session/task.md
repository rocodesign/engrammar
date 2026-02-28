# Task: Deduplicate Lesson Injection Globally Per Session

- Priority: High
- Complexity: C1 (low-hanging)
- Status: Open

## Problem

The hook injects 2 engrams per event (PreToolUse, UserPromptSubmit, etc.). `session_shown_engrams` tracks what was shown but only deduplicates within the same hook event type. The same engram gets injected multiple times across different hook events in the same session, wasting context tokens.

In a typical session with ~30 hook events, the same ~15-20 "relevant" engrams rotate, causing engrams to repeat 3-5x each. This wastes ~2-3k tokens per session for zero new information after the first showing.

## Fix

1. Before injecting a engram, check `session_shown_engrams` for the current `session_id` globally — if the engram was already shown in any hook event this session, skip it.
2. The `get_shown_engram_ids(session_id)` function already exists and returns all shown engram IDs for a session. The hook code just needs to use it as a global filter, not per-event.
3. Once all engrams in the pool have been shown, the hook can either inject nothing or fall back to the highest-relevance already-shown engram (configurable).

## Files

- `src/hook_utils.py` — engram selection logic, add global dedup check
- `hooks/on_prompt.py`, `hooks/on_tool_use.py` — wherever engrams are selected for injection
