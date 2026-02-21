# Idea: SessionEnd Reflection

Prompt the model (or user) with structured questions at session end to capture engrams that weren't extracted in real-time:

- "What did you learn in this session that future sessions should know?"
- "Were there any corrections or surprises worth remembering?"
- "Did you discover any project conventions or tooling quirks?"

## Implementation Options

1. **SessionEnd hook** — inject a reflection prompt at session close, model calls `engrammar_add` with results
2. **CLI command** (`engrammar reflect`) — user-triggered, walks through questions interactively
3. **Passive prompt** — append a gentle reminder to the MCP instructions ("Before the session ends, consider whether anything learned should be saved")
