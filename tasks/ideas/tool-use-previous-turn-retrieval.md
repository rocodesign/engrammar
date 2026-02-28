# Tool-Use Previous Turn Retrieval for Extraction

## Problem

The per-turn extraction pipeline sees ~2000 chars of prior context — a fixed tail, not a coherent previous turn. This makes it hard to detect inflection points (user corrections, redirections, pivots) because the extractor can't see what the assistant said before and how the user reacted to it.

## Idea

Give the extraction LLM a tool (`retrieve_previous_turn`) it can call on-demand during extraction. Instead of always expanding the context window, the LLM decides when more context is needed.

### How it works

1. Pass the current context window to Haiku as today (prior tail + new content)
2. Add a tool definition to the API call: `retrieve_previous_turn` (no args)
3. If the LLM sees signals in the current user prompt suggesting a correction or reaction to a prior response, it calls the tool
4. Tool handler reads backwards from the current byte offset in the JSONL to return the full previous assistant+user exchange
5. Re-call the API with the tool result injected, extraction continues with richer context
6. If the LLM doesn't call the tool, proceed as normal — same cost as today

### Prompt guidance

The extraction prompt would include something like: "If the user appears to be correcting, redirecting, or reacting to a previous response, use `retrieve_previous_turn` to understand what changed."

### What the tool returns

The full previous user+assistant pair — the assistant response that got corrected AND the user message before it (which may contain the original intent that was misunderstood).

## Why this approach

- **No heuristics**: Can't reliably detect inflection signals without the LLM, so regex/keyword approaches are fragile
- **Pay only when needed**: Most turns won't trigger the tool call — one API call, same cost as today
- **Marginal cost is small**: Inflection turns cost two Haiku calls — cheap
- **LLM judges context need**: The model already sees the user prompt and can naturally decide if more context would help
