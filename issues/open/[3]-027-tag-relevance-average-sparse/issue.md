# Issue #27: Tag Relevance Average Uses Sparse Rows Only

- Severity: Medium
- Complexity: C1 (Low complexity, low-hanging)
- Status: Open

## Problem
Average relevance divides by matched DB rows, ignoring missing environment tags as implicit zero.

## Why It Matters
Can over-boost lessons with one known positive tag in a multi-tag environment.

## Suggested High-Level Solution
1. Compute average over full `env_tags` set (missing tag score = 0).
2. Keep current behavior behind a feature flag if migration risk exists.
3. Validate ranking impact with before/after snapshots.
4. Add targeted search ranking tests.
