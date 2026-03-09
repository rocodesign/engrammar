# Task: Normalize and blend scoring with configurable weights

- Priority: High
- Complexity: C2
- Status: Open

## Problem

The current ranking system uses multiplicative tag affinity (`score * multiplier`) which lets tag matching overpower semantic relevance. A badly-tagged engram with high tag similarity can rank above a semantically strong match with low tag similarity. The individual signals (BM25, embedding similarity, tag affinity) are entangled and not independently tunable.

Example from staff-portal eval: EG#1 (Jira skill, unrelated to query) scores 0.0376 while EG#40 (actual extraction engram) scores 0.0183 — a 2x gap caused entirely by tag affinity, not semantic relevance.

## Fix

### 1. Normalize each signal to 0-1

Instead of fusing raw scores multiplicatively, normalize each signal within the result set:

```python
# After RRF fusion, split back into component signals
bm25_norm = bm25_score / max_bm25    # 0-1
embed_norm = embed_score / max_embed  # 0-1
tag_norm = max(0, min(1, (sim - 0.65) / 0.30))  # 0.65→0, 0.95→1.0
```

Engrams with no prerequisite tags get `tag_norm = 0.5` (neutral, not penalized).

### 2. Configurable blend weights

Add weights to `config.yaml` under a new `scoring` section:

```yaml
scoring:
  weight_bm25: 0.25
  weight_embed: 0.35
  weight_tag: 0.40
```

Final score: `w_bm25 * bm25_norm + w_embed * embed_norm + w_tag * tag_norm`

Weights must sum to 1.0. This gives explicit control over how much each signal contributes.

### 3. Expose in eval script

Update `eval_tag_penalty.py` to test different weight combinations instead of (or in addition to) multiplier ranges. Show per-engram breakdown of each normalized component.

## Architecture change

Currently the pipeline is:
```
BM25 + Vector → RRF fusion → tag affinity multiplier → results
```

New pipeline:
```
BM25 (normalize) ─┐
Vector (normalize) ─┤→ weighted sum → results
Tag sim (normalize) ┘
```

This replaces both the RRF fusion step and the tag affinity multiplier with a single weighted blend. RRF is no longer needed because normalization + weighting achieves the same goal with more control.

Alternative: keep RRF for BM25+Vector, then blend the RRF score with tag_norm:
```
BM25 + Vector → RRF fusion (normalize) ─┐
Tag sim (normalize) ─────────────────────┘→ weighted sum → results
```

This is simpler and preserves the existing RRF tuning. Weights would be:
```yaml
scoring:
  weight_semantic: 0.60  # RRF of BM25 + vector
  weight_tag: 0.40       # tag affinity
```

## Files

- `src/core/config.py` — add `scoring` section with weight defaults
- `src/search/engine.py` — replace multiplicative tag boost with normalized blend
- `scripts/eval_tag_penalty.py` — update to test weight combinations

## Validation

- Run eval for both engrammar and staff-portal environments
- Verify that in-domain engrams still rank highest for matching queries
- Verify that EG#1-like outliers (wrong tags, right tag similarity) drop significantly
- Verify that engrams without tags aren't unfairly penalized
- Compare ranking stability across different weight configurations
