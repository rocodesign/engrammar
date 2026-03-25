# Task: Rebalance tag affinity and feedback scoring

- Priority: High
- Complexity: C2
- Status: Open

## Problem

Two scoring components are broken in different ways:

### 1. Tag affinity gives the same bonus to every engram

All engrams with at least one matching tag get the same 0.250 bonus regardless of how many tags match or how well. The formula uses only `best_sim` (the single highest cosine similarity across all prompt-tag × engram-tag pairs), which is always ~1.0 when there's an exact tag match.

Real example — query "cypress testing snapshot", prompt tags `[snapshots, cypress]`:

```
EG#384 [cypress, testing, upgrade]     tag_affinity=0.250  (cypress=1.00, testing=0.62, upgrade=0.60)
EG#181 [cypress, lazy-loading, react]  tag_affinity=0.250  (cypress=1.00, lazy-loading=0.58, react=0.62)
EG#165 [cypress, graphql, mocking]     tag_affinity=0.250  (cypress=1.00, graphql=0.61, mocking=0.57)
```

All three get 0.250 even though EG#384 has more relevant tags (testing, upgrade) than EG#181 (lazy-loading, react).

**Root cause:** The linear ramp from floor (0.45) to ceiling (0.75) gives 57% credit to noise (sim=0.62) vs 100% for a real match (sim=1.00). The noise band (0.55-0.65) is where most unrelated single-word tags land in fastembed's embedding space.

**Fix:** Apply a squared (or steeper) curve to per-tag similarities, then sum across all tags (normalized by tag count so engrams with 5 tags don't dominate over engrams with 3). With a squared curve, noise (0.62) gets only 10% credit vs a real match — effectively zero contribution. Only true matches matter.

Similarity matrix stats (top 30 tags, 435 pairs):
- Median similarity: 0.567
- 75th percentile: 0.603
- Only 13/435 pairs (3%) score above 0.70
- Everything between 0.50-0.65 is noise

### 2. Feedback delta is negligible

Real example — EG#107 with 16 positive evaluations:

```
EG#107  score=1.160
  RRF=0.908  tag_affinity=0.250  feedback=+0.0018
```

Feedback contributes 0.0018 out of 1.160 — that's 0.15%. Even after 16 positive evals, feedback is invisible.

**Why it's so small:**

```
Claude score +2  →  normalized: 0.667  →  attribution: happo=0.667
  × EMA 0.3     →  stored: 0.200 (round 1), max ~0.65 after many rounds
  ÷ 3.0         →  0.022
  × weight 0.20 →  feedback_delta = 0.004
```

The score is divided by 3 twice — once during eval normalization (`score/3.0`) and once at search time (`avg_score / 3.0`). Combined with EMA dampening and weight_feedback=0.20, the max possible feedback delta is ~0.025 even after many evals.

**Target:** One positive feedback should improve ranking by ~5% of a typical score (~1.25), meaning delta ≈ 0.06. Current max is 0.025 — needs ~2.5x increase.

**Fix:** Remove the redundant `/3.0` at search time. BUT — the current `weight_feedback=0.20` was tuned by the search autoresearch sweep with the `/3.0` in place. Removing it requires re-running the full parameter sweep to find the right `weight_feedback` alongside all other scoring params.

## Approach

This needs a combined autoresearch sweep that tests tag affinity curve + feedback weight together:

### Step 1: Implement squared per-tag affinity

Replace `best_sim → ramp → bonus` with `sum(curve(per_tag_sim)) / n_tags → bonus`:

```python
# Per engram tag: apply squared curve
for et in engram_tags:
    sim = best_cosine_sim(et, prompt_tag_embs)
    norm = max(0, (sim - floor) / (1.0 - floor))
    tag_bonus += norm ** 2
# Normalize by tag count
tag_affinity = w_content * (tag_bonus / len(engram_tags))
```

### Step 2: Remove /3.0 from feedback delta

```python
# Old: feedback_delta = (avg_score / 3.0) * weight_feedback
# New: feedback_delta = avg_score * weight_feedback
```

### Step 3: Re-run search autoresearch sweep

Sweep all scoring params together with the new formulas:
- `weight_content_tag` (tag affinity weight)
- `weight_feedback` (will need to be lower without /3.0)
- `tag_sim_floor` / `tag_sim_ceiling`
- `repo_match_boost` / `repo_mismatch_penalty`

### Step 4: Run attribution benchmark

Verify feedback signal is meaningful after the changes.

## Validation

- Tag affinity should differentiate engrams with more matching tags
- Feedback delta after 1 positive eval should be ~5% of typical score
- Search autoresearch composite score should not regress
- Attribution benchmark should show improvement

## Context from analysis (2026-03-26)

Score landscape for a typical query:
- Top 3 results: RRF ~0.9 (strong semantic match), total ~1.2
- Results 4-10: RRF ~0.04 (weak semantic match), total ~0.29
- Gap between tiers: ~0.85 (feedback can never bridge this — by design)
- Gap within tier 2: ~0.01-0.02 (feedback can reorder here)

76% of rank gaps between expected engrams are <0.03 — current feedback can bridge these.
92% are <0.09 — feedback without /3.0 could bridge these.

## Depends on

- #030 (done) — weighted attribution
- #031 (done) — dedup context preservation

## Files

- `src/search/engine.py` — tag affinity formula + feedback delta formula
- `benchmark/run_search_autoresearch.py` — add new params to sweep
- `benchmark/run_attribution_benchmark.py` — validate feedback signal
