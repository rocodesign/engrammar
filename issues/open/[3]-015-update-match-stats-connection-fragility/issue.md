# Issue #15: `update_match_stats` Connection/Transaction Fragility

- Severity: Medium
- Complexity: C2 (Medium complexity)
- Status: Open

## Problem
`update_match_stats` commits mid-function, then calls helper logic via a separate DB connection.

## Why It Matters
Works today, but transaction boundaries are implicit and fragile.

## Suggested High-Level Solution
1. Use one explicit transaction per `update_match_stats` call.
2. Refactor helper logic to accept a connection/cursor instead of opening a new connection.
3. Commit once at the end.
4. Add regression tests for auto-pin behavior under concurrent updates.
