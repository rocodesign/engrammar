# Issue #22: CLI `update --category` Does Not Sync `level1/2/3`

- Severity: Medium
- Complexity: C1 (Low complexity, low-hanging)
- Status: Open

## Problem
CLI category updates set `category` but do not update `level1`, `level2`, `level3`.

## Why It Matters
Category stats and filters can drift from the primary category field.

## Suggested High-Level Solution
1. Reuse the same category parsing logic as MCP `engrammar_update`.
2. Update `category` + `level1/2/3` in one query.
3. Add tests covering CLI category update and category stats consistency.
