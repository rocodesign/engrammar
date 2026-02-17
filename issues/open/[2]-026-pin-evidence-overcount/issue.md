# Issue #26: Pin/Unpin Evidence Can Be Overcounted

- Severity: High
- Complexity: C3 (High complexity)
- Status: Open

## Problem
Evidence threshold sums per-tag counters, so one multi-tag evaluation can advance evidence too quickly.

## Why It Matters
Auto-pin/unpin decisions may trigger with less true session evidence than intended.

## Suggested High-Level Solution
1. Track evaluation events at session granularity (one evidence increment per evaluation event).
2. Keep tag scores for relevance, but decouple from evidence counting.
3. Recompute pin/unpin criteria using event count + score thresholds.
4. Add tests for single-event multi-tag scenarios.
