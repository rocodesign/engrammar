# #37 Progressive disclosure — summarize long engrams, expand on demand

**Severity:** High
**Complexity:** C3

## Problem

All engrams are injected at full length. As engrams grow richer (especially with procedural content from #34), token cost per injection increases. The agent sees the full text even when a summary would suffice to decide relevance.

## Impact

- Token waste on long engrams the agent may not need in full
- Context window pressure in sessions with many surfaced engrams
- No way for the agent to "drill down" into an engram it finds relevant

## Proposed Solution

Two-phase approach:

### Phase 1: Summary generation during extraction/dedup
- During extraction or deduplication, evaluate whether an engram needs a summary
- If the engram exceeds a threshold (e.g. 200 chars), generate a one-line summary
- Store the summary alongside the full text in the DB

### Phase 2: Inject summary, allow expansion
- Hook injection surfaces the summary + a marker indicating the engram is expandable
- The ENGRAMMAR_V1 block indicates which engrams have full content available
- The agent can call a new MCP tool (e.g. `engrammar_expand(engram_id)`) to retrieve full text
- Or: include the expansion hint in the existing block format, e.g.:
  ```
  - [EG#42][summary] Use pytest fixtures for DB setup (expand: engrammar_expand(42) for full procedure)
  ```

### Tuning considerations
- Threshold for "needs a summary" — short factual engrams don't need one
- Summary quality — must preserve enough signal for the agent to decide if it needs the full text
- Which engrams are expandable — procedural ones (#34), long ones, or all above threshold

## Notes

- Pairs directly with #34 (procedural engrams would be the primary beneficiaries)
- Hermes uses a 3-level progressive disclosure pattern (list → view → view reference files)
- The tricky part is tuning when summaries help vs hurt — too aggressive and the agent misses context
