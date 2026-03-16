# #33 Inject engrams when the agent plans or executes multi-step work

**Severity:** High
**Complexity:** C1 (low-hanging)

## Problem

During long autonomous sessions where the agent plans and executes multi-step work, there is no mechanism to surface relevant engrams for each step. Hooks only fire on user prompts and tool calls — but when the agent is working through a plan by itself, there are no user prompts to trigger injection. Tool-use hooks help somewhat but miss the planning phase entirely.

This means the agent can execute entire workflows without benefiting from engrams that would be relevant to specific steps in its plan.

## Impact

- Long autonomous sessions (the most complex work) get the least engram support
- Agent may repeat mistakes or miss conventions that engrams would have caught
- High-value engrams go unsurfaced during exactly the sessions where they matter most

## Proposed Solution

Add instructions (via MCP server instructions, session-start injection, or both) that tell the agent:

> When planning multi-step work, search engrams relevant to each step before executing it.

This leverages the existing `engrammar_search` MCP tool — no new infrastructure needed. The agent just needs to be told to proactively pull engrams as part of its planning/execution workflow.

Options:
1. Add to MCP server instructions (affects all sessions)
2. Add to session-start pinned context
3. Both — instructions in MCP + a pinned engram reinforcing the behavior

## Notes

- This is high-value because autonomous sessions are where the agent does the most complex work
- Low complexity because it's instruction-based, not code-based
- Inspired by the gap between hook-driven injection and agent-driven retrieval
