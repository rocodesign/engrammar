# Task: Incremental Embedding Index Update

- Priority: Medium
- Complexity: C2
- Related issue: `issues/open/[3]-033-incremental-embedding-index-update/issue.md`
- Status: Open

## Problem

`build_index` recomputes embeddings for all active lessons on every add/update. O(n) in lesson count, requires loading the embedding model each time. Overlaps with issue #12 but also covers text updates from refinement (#32).

## Fix

1. **`update_embedding(lesson_id, text)`**: Embed just the changed text, find position in ID array, replace that row in the numpy matrix, save.
2. **`append_embedding(lesson_id, text)`**: For new lessons, embed and append vector + ID rather than rebuilding.
3. **Keep full rebuild**: `engrammar rebuild` stays as a CLI maintenance command for periodic cleanup or after bulk operations.
4. **Lazy model caching**: If running in daemon mode, cache the loaded model to avoid repeated import overhead.

## Files

- `src/embeddings.py` — `update_embedding`, `append_embedding` functions
- `src/extractor.py` — callers switch from `build_index` to incremental
- `cli.py` — callers in `cmd_add`, `cmd_update` switch to incremental
