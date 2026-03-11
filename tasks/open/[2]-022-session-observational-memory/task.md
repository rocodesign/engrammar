# Task: Add Session Observational Memory Layer

- Priority: Medium
- Complexity: C3
- Status: Open

## Problem

Engrammar currently learns from raw transcript slices:

- per-turn extraction reads a fixed prior tail plus the new transcript delta
- evaluation reads a head+tail excerpt of the session transcript
- tool-use search has little awareness of the current task beyond tool arguments

That loses session-level state such as:

- the current goal after several pivots
- approaches that were tried and rejected
- user corrections that only make sense relative to earlier turns
- temporary decisions, blockers, and open questions

The result is avoidable context loss for extraction, evaluation, and search-query construction.

## Goal

Introduce a **session-scoped observational memory layer** that continuously distills the active conversation into compact observations. Use it to improve extraction and evaluation quality without replacing engrams as the durable cross-session knowledge store.

## Design

### 1. Keep observational memory separate from engrams

Observation records are session-local and volatile. They should capture things like:

- current task / subtask
- recent decisions
- user corrections and preferences
- failed approaches
- unresolved blockers

These records are input to learning, not durable knowledge to inject globally by default.

### 2. Build observations in the background

Add a background processor, triggered from the existing Stop-hook / daemon flow, that:

1. reads the new transcript delta
2. combines it with the prior session summary
3. emits updated observations and a compact rolling summary

This should stay asynchronous so hook latency remains low.

### 3. Preserve evidence links

Observations should keep lightweight references to their supporting transcript region (for example offsets, message ids, or short excerpts). Consumers need a way to inspect evidence instead of trusting a lossy summary blindly.

### 4. Use it as an upstream signal

Primary consumers:

1. **Extractor**
   - use rolling session summary + targeted evidence windows instead of only fixed-tail transcript context
2. **Evaluator**
   - judge shown engrams against compact session state plus evidence-rich windows, not only head/tail excerpts
3. **Search query construction**
   - optionally blend the current task summary into prompt/tool-use retrieval when it improves precision

### 5. Preserve the promotion boundary

Observation-derived content should still flow through the existing extraction, dedup, staging, and evaluation pipeline before it becomes a durable engram. Raw observations should not bypass `#012` and become globally injectable knowledge automatically.

## Non-goals

- replacing the engram database or hybrid search stack
- storing every transcript detail permanently
- turning session state into immediately searchable global memory
- removing candidate/staging safeguards for auto-extracted engrams

## Suggested Implementation Order

1. Add persisted session observation / summary tables and DB helpers
2. Add a background observation processor to the daemon / Stop-hook path
3. Feed observation summaries into extraction
4. Feed observation summaries into evaluation
5. Test whether prompt/tool-use retrieval improves when query construction uses current session summaries

## Related Work

- `tasks/open/[2]-016-adaptive-evaluation-transcript-context/task.md`
- `tasks/open/[2]-012-stage-auto-extracted-engrams/task.md`
- `tasks/ideas/session-end-reflection.md`
- `tasks/ideas/tool-use-previous-turn-retrieval.md`

## Open Concerns

1. **Cost vs payoff** — Adds an LLM call (Haiku) per turn just to maintain a rolling summary, doubling per-turn LLM spend alongside extraction. Need evidence that current fixed-tail context actually causes bad extractions often enough to justify this.

2. **Narrower win than it appears** — Mastra's OM compresses conversation history for the model itself. Here, Claude already sees its own conversation — the observation layer only helps engrammar's background pipelines (extractor, evaluator) see better context.

3. **Try simpler alternatives first** — Before building a full observation layer:
   - Give the extractor a larger context window (increase tail size)
   - Pass full transcript to evaluation instead of head+tail excerpts
   - These are zero-cost changes that might solve 80% of the context loss problem

4. **Collect failure evidence** — Gather concrete examples of extractions that failed due to insufficient session context before committing to C3 work.

## Files

- `src/core/db.py` — observation/session-summary persistence
- `src/infra/daemon.py` — background scheduling
- `hooks/on_stop.py` — trigger observation updates
- `src/pipeline/extractor.py` — consume observation summaries during per-turn extraction
- `src/pipeline/evaluator.py` — consume observation summaries during relevance evaluation
- `src/search/engine.py` — optional query enrichment from current session state
