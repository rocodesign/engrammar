# Task: LLM-Assisted Engram Refinement on Merge

- Priority: Medium
- Complexity: C2
- Related issue: `issues/open/[3]-032-llm-assisted-engram-merge/issue.md`
- Blocked by: #003 (stronger dedup), #005 (incremental index)
- Status: Open

## Problem

When duplicates merge, only `occurrence_count` bumps — text never improves. Early-extracted engrams stay vague even when later occurrences express the insight more concretely.

## Fix

1. **Threshold trigger**: Refine only when `occurrence_count` crosses 3+. Keeps common path cheap and deterministic.
2. **Refinement prompt**: Send original text + source transcript snippets to Haiku with constraints:
   - "Keep all specific commands, tool names, paths, and flags."
   - "Never replace concrete examples with abstract summaries."
   - "Output must be 1-2 sentences max."
3. **Specificity guard**: Before accepting, verify backtick code spans and specific commands from original are present in output. Reject and keep original if dropped.
4. **Audit trail**: Store previous text version in a `engram_history` table so refinements are traceable.
5. **Incremental index**: Update only the refined engram's embedding (depends on #005).

## Files

- `src/extractor.py` — refinement logic in merge path
- `src/db.py` — `engram_history` table, migration
- `cli.py` — optional `refine` command for manual trigger
