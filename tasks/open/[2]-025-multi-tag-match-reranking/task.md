# Task: Multi-Tag Match Count for Reranking

- Priority: Medium
- Complexity: C1
- Status: Open

## Problem

The tag affinity score uses only the single best prompt-tag × engram-tag similarity (`sim_matrix.max()`). An engram matching 3 out of 3 prompt tags at 0.70 each ranks similarly to one matching 1 out of 3 at 0.75. The multi-topic signal is lost.

Example: query "happo cypress CI failure" detects prompt tags `[happo, cypress, ci]`. An engram about happo+cypress compatibility (matching all 3 tags) should rank higher than one about generic CI config (matching only `ci`), but `max()` doesn't differentiate.

## Proposed approach

Modify `compute_tag_affinity` (both in `engine.py` and autoresearch's `PrecomputedData`) to consider match breadth:

### Option 1: Mean of top-k similarities
```python
# Instead of: best_sim = sim_matrix.max()
# Use: mean of per-prompt-tag best matches
per_prompt_best = sim_matrix.max(axis=1)  # best engram-tag match per prompt-tag
best_sim = per_prompt_best.mean()
```

### Option 2: Count-weighted bonus
```python
best_sim = sim_matrix.max()  # keep for thresholding
match_count = (sim_matrix.max(axis=1) >= tag_sim_floor).sum()
match_ratio = match_count / len(prompt_tag_indices)
tag_bonus = tag_bonus * (0.5 + 0.5 * match_ratio)  # boost for breadth
```

### Option 3: Sweep parameter `tag_match_mode`
Add to autoresearch grid: `"max"` (current), `"mean"`, `"count_weighted"`. All pre-computable from the existing `sim_matrix`.

## Autoresearch testing

This requires minimal change to `compute_tag_affinity` in the benchmark. The sim_matrix is already computed per engram. Add `tag_match_mode` to the param grid and measure which mode improves P@1.

## Expected impact

+2-3% P@1 for multi-topic queries. No impact on single-topic queries (all modes equivalent with 1 prompt tag).

## Files

- `benchmark/run_search_autoresearch.py` — `compute_tag_affinity` method in `PrecomputedData`
- `src/search/engine.py` — tag affinity section (step 3.6), if productionized
