# Idea: Minimum Similarity Floor for Search Results

Add minimum quality thresholds to vector search and BM25 before feeding into RRF, so completely irrelevant engrams never enter the ranking pipeline.

## Problem

Currently RRF always returns top_k results regardless of actual relevance. For vague queries like "how do I deploy this", all results are noise (vector sim ~0.62, no engram is actually relevant) but they still get injected.

## Evidence from testing

- **Vector similarity range**: 0.58-0.74 across all queries. Relevant matches tend to be 0.65+, noise sits at 0.58-0.63. Tight spread makes a clean cutoff hard.
- **BM25 scores**: much more spread (0.99-5.77 for one query). Top results cluster, then sharp drop-off.
- Query "how do I deploy this" returned Jira and CameraTag engrams at sim=0.63 — total noise but scores look similar to relevant matches.

## Proposed approach

Filter each list before RRF:

```python
# Vector: absolute cosine floor
vector_results = [(lid, sim) for lid, sim in vector_results if sim >= VECTOR_FLOOR]

# BM25: relative floor (% of best score for this query)
if bm25_ranked:
    bm25_max = bm25_ranked[0][1]
    bm25_ranked = [(lid, sc) for lid, sc in bm25_ranked if sc >= bm25_max * BM25_RATIO]
```

Engram weak in both lists never enters RRF. Strong in one but weak in the other still gets through with a lower RRF score (appears in fewer lists).

## Open questions

- Vector floor: 0.45 (very permissive) vs 0.55 (still permissive) vs 0.62 (aggressive). The tight similarity range makes tuning delicate.
- BM25 ratio: 0.3 (30% of max) seems reasonable from observed score distributions.
- Should we return zero results when nothing passes the floor? Currently hooks always inject something if search returns anything — an empty result would be a behavior change (probably a good one).

## Update (2026-03-22): Partially implemented, sweep data available

`min_vector_sim` is now a sweep parameter in autoresearch. Latest sweep found `min_vector_sim=0.65` as the best single lever for abstention — it lifts abstain accuracy from 50% to 70% while only costing ~4% P@1 (57%→52%).

**What's still open:**
- **Pre-RRF filtering** (the original proposal) hasn't been tested — current `min_vector_sim` is applied post-search as an abstention gate, not as a pre-RRF filter. Pre-RRF filtering would change which engrams enter fusion, potentially different results.
- **BM25 relative floor** hasn't been implemented or swept. Could be an orthogonal abstention signal (see new task #026 for BM25 token overlap approach).
- **Finer granularity sweep** around the 0.60-0.70 range would help find the sweet spot — current grid steps are [0.55, 0.60, 0.65, 0.70], could benefit from 0.62/0.67 points.

The core insight from the original idea holds: the tight vector similarity range (0.58-0.74) makes a clean cutoff hard. The sweep confirmed this — 0.65 is a compromise that trades some recall for much better abstention.
