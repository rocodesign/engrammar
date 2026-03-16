# #38 Session-level capacity limits for surfaced engrams

**Severity:** Medium
**Complexity:** C2

## Problem

There is no global cap on how many engrams can be surfaced in a single session. The per-hook limits (`max_engrams_per_prompt`, `max_engrams_per_tool`) constrain individual injections, but across a long session with many prompts and tool calls, the cumulative token cost of injected engrams can grow significantly.

The existing deduplication and evaluation pipeline handles long-term quality, but doesn't address per-session volume.

## Impact

- Long sessions accumulate many injected engrams, adding token overhead
- No way to prioritize which engrams are most important for a given session
- Diminishing returns — after N engrams, additional ones are less likely to be novel/useful

## Proposed Solution

Add session-level limits:

1. **Max engrams per session**: Cap the total number of unique engrams surfaced across all hooks in one session (e.g. 15-20)
2. **Estimated token budget**: Cap based on estimated tokens rather than count, since engram lengths vary
3. **Priority ordering**: When approaching the cap, surface only higher-scoring engrams

Implementation:
- The `shown_engrams` DB table already tracks what was surfaced per session
- Hooks can check the count before injecting and skip if at capacity
- Config options: `max_engrams_per_session`, `max_tokens_per_session` (estimated)

## Notes

- This is different from Hermes's fixed-size MEMORY.md approach — we're limiting per-session injection volume, not total corpus size
- The dedup and evaluation pipeline already handles corpus quality; this handles session-level noise
- Should be configurable so power users can raise/lower the limits
