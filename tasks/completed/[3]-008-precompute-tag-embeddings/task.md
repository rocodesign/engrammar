# Task #008: Precompute and Cache Tag Embeddings

**Priority:** Low `[3]`
**Complexity:** C1
**Status:** Complete
**Promoted from:** `tasks/ideas/precompute-tag-embeddings.md`

## Problem

The tag vector affinity boost (search.py step 3.1) calls `embed_text(" ".join(engram_tags))` for every candidate engram on every search. With 51 engrams this adds ~1s of embedding overhead per search.

## Solution

Precompute engram tag embeddings during index build and store them as `tag_embeddings.npy` + `tag_embedding_ids.npy`. At search time, load the precomputed array and do a single vectorized cosine similarity instead of per-engram embed calls.

## Changes

1. `config.py` — add `TAG_INDEX_PATH` and `TAG_IDS_PATH` constants
2. `embeddings.py` — add `build_tag_index()` and `load_tag_index()` functions
3. `search.py` — replace per-engram `embed_text()` with vectorized lookup from precomputed tag index
4. `cli.py` — rebuild tag index in `setup`, `rebuild`, `add`, `update --prereqs`, and `backfill-prereqs`
