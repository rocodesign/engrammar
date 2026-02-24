# Task: Extract Engrams at Session End

- Priority: High
- Complexity: C2 (medium)
- Status: Completed

## Problem

After the initial batch extraction catches up on historical transcripts, ongoing engram learning relies on the model voluntarily calling `engrammar_add` via MCP instructions. This is unreliable — the model often doesn't do it, so friction and corrections go uncaptured.

The only fallback is manually re-running `engrammar extract`, which processes transcripts after the fact.

## Solution (Implemented)

Replaced the unreliable SessionEnd hook with a Stop hook that fires after every assistant response. This gives incremental, per-turn extraction using byte offsets — more reliable than session-end (which doesn't fire on terminal close).

### What was done

1. **Created `hooks/on_stop.py`** — Stop hook entry point. Sends `process_turn` request to daemon, falls back to direct CLI spawn. Writes session audit for shown engrams.
2. **Added `extract_from_turn()` to `src/extractor.py`** — Offset-based transcript reading. Only processes new content since last turn. Reuses existing extraction pipeline (Haiku call, dedup, prerequisites).
3. **Added `process_turn` handler to `src/daemon.py`** — Single-flight via `extract_proc`. If previous turn's extraction is still running, returns `"already_running"`.
4. **Added `process-turn` CLI command to `cli.py`** — Calls `extract_from_turn()` then runs evaluation.
5. **Updated `src/register_hooks.py`** — Registers Stop hook, removes SessionEnd hook, cleans up old hooks.
6. **Deleted `hooks/on_session_end.py`** — Replaced by Stop hook.
7. **Added offset cleanup to SessionStart** — Deletes turn offset files older than 24h.

### Key design decisions

- **Byte offsets** stored in `~/.engrammar/.turn_offsets/<session_id>` — plain int files, cleaned up after 24h
- **Prior context** — reads ~2000 chars before offset for continuity so Haiku has conversation context
- **Single-flight concurrency** — daemon reuses `extract_proc`, skips if already running, next turn catches up
- **10KB threshold** — skips small transcripts (agent/subagent sessions)

## Files

- `hooks/on_stop.py` — Stop hook entry point (new)
- `hooks/on_session_end.py` — deleted
- `hooks/on_session_start.py` — added offset cleanup
- `src/extractor.py` — added `extract_from_turn()`, offset functions, `cleanup_old_turn_offsets()`
- `src/daemon.py` — added `process_turn` handler
- `cli.py` — added `process-turn` command
- `src/register_hooks.py` — Stop hook registration, SessionEnd removal
