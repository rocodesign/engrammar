# Task: Coalesce Queued Turn Extraction Requests

- Priority: High
- Complexity: C2
- Status: Completed

## Problem

The Stop hook triggers `process_turn` after every assistant response, but the daemon ran a single extraction job and returned `already_running` while active. Under sustained activity, turn extraction requests got dropped instead of queued.

## Solution (Implemented)

Added a coalescing queue (`_pending_turns`) to the daemon:

1. **`_pending_turns` dict** — `{session_id: transcript_path}`, coalesced per session (latest transcript path wins)
2. **Queue on busy** — `process_turn` handler checks if `extract_proc` is running; if so, adds to `_pending_turns` and returns `{"status": "queued"}`
3. **`_drain_pending_turns()`** — pops first pending session when `extract_proc` finishes, starts extraction. Called after every connection and on 5s timeout polls in the main loop.
4. **Byte offsets** — each drain run catches all accumulated content since last saved offset
5. **Logging** — queue and drain events logged with session ID prefix and pending count

## Files

- `src/daemon.py` — `_pending_turns`, queue logic in `process_turn`, `_drain_pending_turns()`, drain calls in main loop
- `tests/test_daemon.py` — 6 new tests covering queue, coalesce, drain, sequential drain
- `docs/ARCHITECTURE.md` — updated concurrency docs
