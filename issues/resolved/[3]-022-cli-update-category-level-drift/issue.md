# Issue #22: CLI `update --category` Does Not Sync `level1/2/3`

- Severity: Medium
- Complexity: C1 (Low complexity, low-hanging)
- Status: Resolved

## Problem
CLI category updates set `category` but do not update `level1`, `level2`, `level3`.

## Why It Matters
Category stats and filters can drift from the primary category field.

## Suggested High-Level Solution
1. Reuse the same category parsing logic as MCP `engrammar_update`.
2. Update `category` + `level1/2/3` in one query.
3. Add tests covering CLI category update and category stats consistency.

## Resolution
Implemented in `cli.py`:

1. `cmd_update --category` now reuses `_parse_category()` from `src.core.db`.
2. The CLI update query now writes `category`, `level1`, `level2`, and `level3` together, matching the MCP path.
3. Added regression test `test_cmd_update_category_syncs_levels` in `tests/test_cli.py` to verify:
   - primary category is updated
   - `level1/2/3` stay in sync
   - the category junction table drops the old category and keeps the new one
