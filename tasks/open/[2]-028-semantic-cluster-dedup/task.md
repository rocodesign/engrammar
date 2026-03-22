# Task: Semantic Cluster Deduplication

- Priority: Medium
- Complexity: C3
- Status: Open

## Problem

Current dedup is pairwise: for each unverified engram, find top-k similar verified engrams and ask the LLM to decide. This misses transitive duplicates: if A≈B (sim 0.75) and B≈C (sim 0.72), but A≈C is only 0.55 (below typical notice), the system won't consider merging A and C even though they're semantically redundant through B.

With ~450 engrams and growing, these transitive clusters accumulate.

## Proposed approach

### 1. Cluster all engrams by embedding similarity

Use agglomerative clustering (or DBSCAN) on engram embeddings:

```python
from sklearn.cluster import AgglomerativeClustering

# Cosine distance matrix
sim_matrix = normed_embeddings @ normed_embeddings.T
distance_matrix = 1 - sim_matrix

clustering = AgglomerativeClustering(
    n_clusters=None,
    distance_threshold=0.40,  # 0.60 cosine sim
    metric="precomputed",
    linkage="average",
)
labels = clustering.fit_predict(distance_matrix)
```

### 2. Present clusters to LLM for merge decisions

Instead of pairwise comparisons, show the LLM an entire cluster:

```
These engrams form a semantic cluster (similarity > 0.60):

1. [#75] "LLM-assisted dedup uses cosine similarity..."
2. [#211] "Pass existing engrams as context to prevent re-extraction..."
3. [#304] "Dedup pipeline merges similar engrams at 0.85 threshold..."

Are any of these true duplicates? If so, which should be the canonical form?
```

### 3. Benefits over pairwise

- Catches transitive duplicates that pairwise misses
- LLM sees full context of related engrams — can make better merge decisions
- Fewer LLM calls (one per cluster vs one per pair)
- Natural grouping reveals "topic neighborhoods" useful for other features

## Risks

- Cluster size varies — very large clusters (10+ engrams) may exceed context or produce poor LLM decisions
- Aggressive clustering could merge related-but-distinct engrams (happo CI vs happo config)
- Requires careful distance_threshold tuning

## Relation to other tasks

- **#027** (dedup benchmark) should be built first — ground truth pairs enable measuring whether cluster-based dedup is actually better than pairwise
- Could reuse cluster analysis for tag vocab normalization (cluster tags the same way)

## Files

- `src/pipeline/dedup.py` — new `dedup_clustered()` function alongside existing `dedup_unverified()`
- `benchmark/run_dedup_benchmark.py` — add cluster mode for comparison
