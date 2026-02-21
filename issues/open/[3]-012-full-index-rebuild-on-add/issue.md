# Issue #12: Full Index Rebuild On Every Add/Deprecate

- Severity: Medium
- Complexity: C3 (High complexity)
- Status: Open

## Problem
Adding/deprecating one engram rebuilds embeddings for the whole corpus.

## Why It Matters
Cost grows with dataset size and can slow user-facing operations.

## Suggested High-Level Solution
1. Add incremental index operations (append/update/remove by engram ID).
2. Keep full rebuild command as a fallback (`engrammar rebuild`).
3. Use periodic compaction/rebuild to avoid index fragmentation.
4. Add integrity check to detect ID/index drift.
