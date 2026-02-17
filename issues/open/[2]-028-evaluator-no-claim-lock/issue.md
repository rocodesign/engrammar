# Issue #28: Evaluator Has No Claim/Lock Step

- Severity: High
- Complexity: C3 (High complexity)
- Status: Open

## Problem
Pending sessions are selected then processed without atomic claim/ownership.

## Why It Matters
Concurrent evaluator runs can process the same session twice.

## Suggested High-Level Solution
1. Add explicit `processing` state with worker claim timestamp.
2. Claim rows atomically before evaluation (single SQL update/select pattern).
3. Add stale-claim timeout and retry recovery.
4. Ensure idempotent status transitions (`pending -> processing -> completed/failed`).
