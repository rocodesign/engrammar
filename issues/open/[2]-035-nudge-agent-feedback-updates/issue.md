# #35 Nudge the agent to provide feedback and update engrams more often

**Severity:** High
**Complexity:** C1 (low-hanging)

## Problem

The MCP instructions tell the agent to call `engrammar_feedback` when an engram doesn't apply and to `engrammar_update` when one could be improved. In practice, agents rarely do this unprompted. The feedback/update loop that improves engram quality over time depends on the agent actually closing the loop.

## Impact

- Engrams that are wrong or stale persist longer than they should
- Tag relevance scoring gets fewer data points, making filtering less accurate
- The self-improvement loop (surface → feedback → refine) is mostly theoretical

## Proposed Solution

Strengthen the nudge in multiple places:

1. **MCP server instructions**: Make the feedback/update expectations more prominent and specific. Add examples of when to call feedback vs update.

2. **Session-start injection**: Add a brief reminder in the pinned context block, e.g.:
   > After using a surfaced engram, call engrammar_feedback to record whether it helped. If it was partially right, call engrammar_update to improve it.

3. **Hook injection footer**: Currently the ENGRAMMAR_V1 block ends with "If one doesn't apply here, call engrammar_feedback(...)". Could expand to also mention update when partially right.

4. **Periodic nudge** (optional, lower priority): At session start or after N turns, inject a gentle reminder to review surfaced engrams.

## Notes

- This is instruction-tuning, not code changes — low complexity
- Hermes uses "periodic nudges" for this exact purpose
- The ROI is high because every feedback call improves future sessions
