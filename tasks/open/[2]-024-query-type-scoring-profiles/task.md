# Task: Query-Type-Aware Scoring Profiles

- Priority: Medium
- Complexity: C2
- Status: Open

## Problem

The search pipeline uses a single set of scoring weights for all query types (prompt, tool, post_tool), but these types have fundamentally different characteristics:

- **Prompt queries** are natural language, benefit from high semantic weight, need strong abstention for filler
- **Tool queries** are synthetic keyword-dense strings (e.g., "editing react typescript component..."), benefit from stronger tag affinity and BM25
- **Post_tool queries** are assistant narrations, often intent-heavy with weak vocabulary overlap (see EG#290)

The ground truth has 35 prompt, 12 tool, and 13 post_tool queries. Bucket metrics from ablation likely show different accuracy profiles per type, but one config compromises across all.

## Proposed approach

### 1. Measure per-type baselines

Run ablation with bucket breakdowns (already supported via `compute_bucket_metrics`). Identify which types underperform and which scoring components help/hurt each type.

### 2. Add query_type to sweep grid

In `run_sweep_fast`, apply different parameter overrides per query type:
- `weight_content_tag_prompt` / `weight_content_tag_tool` / `weight_content_tag_post_tool`
- `min_top1_score_prompt` / `min_top1_score_tool`
- Or simpler: a `tag_weight_multiplier` per type applied to the base `weight_content_tag`

### 3. Optimize independently, then measure combined

Sweep each type's params independently to find per-type optima, then combine and measure the overall composite.

## Expected impact

+3-5% P@1 overall. Tool queries should see the largest improvement since they're the most structurally different from prompts.

## Relation to other tasks

- **#009** (richer tool-use context) improves query *input* quality; this task improves *scoring* per type. Complementary.
- Autoresearch sweep infrastructure already has `query_type` in ground truth labels.

## Files

- `benchmark/run_search_autoresearch.py` — add per-type parameter application in `run_sweep_fast`
- `src/search/engine.py` — if productionized, add query_type parameter to `search()`
