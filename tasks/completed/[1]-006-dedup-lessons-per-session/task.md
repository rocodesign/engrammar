# Task: Deduplicate Lesson Injection Globally Per Session

- Priority: High
- Complexity: C1 (low-hanging)
- Status: Open

## Problem

The hook injects 2 lessons per event (PreToolUse, UserPromptSubmit, etc.). `session_shown_lessons` tracks what was shown but only deduplicates within the same hook event type. The same lesson gets injected multiple times across different hook events in the same session, wasting context tokens.

In a typical session with ~30 hook events, the same ~15-20 "relevant" lessons rotate, causing lessons to repeat 3-5x each. This wastes ~2-3k tokens per session for zero new information after the first showing.

## Fix

1. Before injecting a lesson, check `session_shown_lessons` for the current `session_id` globally — if the lesson was already shown in any hook event this session, skip it.
2. The `get_shown_lesson_ids(session_id)` function already exists and returns all shown lesson IDs for a session. The hook code just needs to use it as a global filter, not per-event.
3. Once all lessons in the pool have been shown, the hook can either inject nothing or fall back to the highest-relevance already-shown lesson (configurable).

## Files

- `src/hook_utils.py` — lesson selection logic, add global dedup check
- `hooks/on_prompt.py`, `hooks/on_tool_use.py` — wherever lessons are selected for injection
