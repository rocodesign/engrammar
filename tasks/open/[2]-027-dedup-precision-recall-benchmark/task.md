# Task: Dedup Precision/Recall Benchmark

- Priority: Medium
- Complexity: C2
- Status: Open

## Problem

The dedup pipeline has no automated quality measurement. We have dedup benchmark results (`benchmark/results/dedup-*`) that test haiku vs sonnet at different similarity thresholds, but no ground truth labels for whether merge decisions were correct.

Without this, we can't:
- Tune `min_sim` threshold (currently 0.50) with evidence
- Measure whether LLM merge decisions are accurate
- Compare dedup strategies (pairwise vs cluster, different prompts)
- Detect regression when changing dedup parameters

## Proposed approach

### 1. Build ground truth dataset

Create `benchmark/dedup_ground_truth.json` with labeled pairs:

```json
{
  "pairs": [
    {
      "engram_a_id": 75,
      "engram_b_id": 211,
      "similarity": 0.82,
      "label": "duplicate",
      "canonical": "a",
      "note": "both about LLM-assisted dedup"
    },
    {
      "engram_a_id": 129,
      "engram_b_id": 162,
      "similarity": 0.45,
      "label": "distinct",
      "note": "TODO lint vs PR template — different domains"
    }
  ]
}
```

Source pairs from:
- `engram_merge_log` — past merge decisions (assumed correct, spot-check)
- Manual review of high-similarity pairs that were NOT merged
- Known false positives from keyword overlap (e.g., EG#275: "duplicate" in different contexts)

### 2. Build benchmark runner

`benchmark/run_dedup_benchmark.py` that:
- Loads ground truth pairs
- Runs dedup decision logic (LLM call or embedding-only) on each pair
- Measures precision (correct merges / total merges) and recall (found duplicates / true duplicates)
- Sweeps `min_sim` threshold to find optimal operating point

### 3. Sweep min_sim threshold

Current threshold is 0.50 (very permissive — sends many non-duplicate pairs to Haiku). Sweep [0.50, 0.55, 0.60, 0.65, 0.70] and measure:
- How many pairs reach the LLM at each threshold (cost proxy)
- Precision/recall at each threshold
- Whether higher thresholds miss transitively-related duplicates

## Expected outcome

An optimal `min_sim` threshold backed by data (likely 0.55-0.60 based on existing dedup benchmark results showing haiku handles well at sim=0.6). Reduced LLM cost from fewer false-positive candidate pairs.

## Files

- `benchmark/dedup_ground_truth.json` — new, labeled pairs
- `benchmark/run_dedup_benchmark.py` — new, benchmark runner
- `src/pipeline/dedup.py` — `min_sim` parameter to tune
