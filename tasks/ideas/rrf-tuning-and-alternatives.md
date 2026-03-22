# Idea: RRF Tuning and Alternative Fusion Strategies

Explore whether RRF is the best fusion approach for a small engram corpus, or if alternatives would give better discrimination.

## Current state

RRF with dynamic k=N/5 (currently k=10 for 51 engrams) gives rank 0 a 1.82x advantage over rank 9. Combined with the tag affinity multiplier (0.3x-1.7x), this produces good results. But RRF has inherent limitations:

## Observations from testing

- **RRF compresses scores by design** — all scores end up in a narrow band (~0.05-0.18 with k=10). The tag multiplier does most of the actual discrimination work.
- **RRF is rank-based, discards magnitude** — a vector similarity of 0.74 (strong match) and 0.60 (weak match) get treated identically if they're both rank 0 in their list. The raw similarity/BM25 scores carry useful information that RRF throws away.
- **With 2 lists and top-10 each, the main RRF signal is "appears in both lists vs one"** — positional differences within a list are secondary.

## Alternative approaches to explore

1. **Weighted score combination** — normalize vector (0-1) and BM25 (divide by max) to same scale, then weighted sum: `0.5 * vector_norm + 0.5 * bm25_norm`. Preserves magnitude information.

2. **Score-aware RRF** — modify RRF to include the raw score: `score / (k + rank + 1)` instead of `1 / (k + rank + 1)`. Rank 0 with high similarity contributes more than rank 0 with low similarity.

3. **Cascade approach** — use vector search as primary (it captures semantic meaning), then BM25 as a tiebreaker/boost for keyword matches.

## Why this might matter

The tag affinity multiplier compensates well for RRF's weaknesses in the current setup. But if we add a similarity floor (see `similarity-floor-threshold.md`), the floor interacts with RRF in complex ways — filtering before fusion vs after fusion produces different results. A fusion method that preserves score magnitude would make the floor more natural.

## Autoresearch testing plan (2026-03-22)

The autoresearch sweep infrastructure can test all three alternatives without modifying production code:

1. **Pre-compute raw scores** — `PrecomputedData` already stores `vector_sim` per result. Add `bm25_score` to the base results so fusion can be re-applied per config.
2. **Add `fusion_mode` to sweep grid** — `"rrf"` (current), `"weighted_sum"`, `"score_aware_rrf"`. Each mode recomputes the base score from raw components.
3. **Measure P@1 lift** — the current P@1→P@3 gap is 19pts (57%→76%), meaning the right answer is usually present but mis-ranked. Score-aware fusion should close this gap by preserving magnitude.

Key observation from latest ablation: RRF normalization (floor=0.015, ceiling=0.033) inflates raw cosine ~0.67 to ~0.95 before blending. This means tag affinity (weight 0.25) operates on an already-inflated base — the effective tag contribution is smaller than intended. Score-aware fusion would make the blend weights behave more predictably.

## Priority

Low — current pipeline works well after the tag affinity boost. Revisit if new scoring signals are added or if edge cases emerge. The autoresearch plan above makes this cheap to test when ready.
