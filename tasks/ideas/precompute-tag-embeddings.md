# Idea: Precompute and Cache Tag Embeddings

Store lesson tag embeddings alongside the lesson embedding index so the tag affinity boost doesn't recompute them on every search.

## Current state

The tag vector affinity boost (step 3.1 in search) calls `embed_text(" ".join(lesson_tags))` for every candidate lesson during search. With 51 lessons this is fast enough (~20ms per embed), but at scale it adds up.

## What to cache

1. **Env tag embedding** — same for the entire session (tags don't change mid-session). Could be computed once at session start and passed through.
2. **Lesson tag embeddings** — change only when lesson prerequisites are updated. Could be stored as a parallel numpy array alongside the existing lesson text embeddings (index.npy / ids.npy).

## Implementation sketch

- During `build_index()` or `rebuild`, also compute and save tag embeddings: `tag_index.npy` + `tag_ids.npy`
- In `search()`, load the tag index and do a single vectorized cosine similarity instead of per-lesson embed calls
- Rebuild tag index whenever `backfill-prereqs` or `update --prereqs` runs

## Priority

Low — the current per-search compute is negligible for <100 lessons. Worth revisiting if lesson count grows past 200+ or search latency becomes noticeable in hooks.
