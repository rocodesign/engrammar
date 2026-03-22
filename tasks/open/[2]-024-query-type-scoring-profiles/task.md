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

## MetaClaw-inspired: Category-based retrieval routing

MetaClaw classifies queries into 9 task categories (coding, security, agentic tasks, communication, etc.) and routes retrieval strategy per category. This is a richer version of query-type profiles.

### Idea: Two-level routing

Level 1 is the existing `query_type` (prompt/tool/post_tool) — structural distinction.
Level 2 is a **semantic category** detected from the query content:

- `debugging` — error messages, stack traces, "why doesn't X work"
- `architecture` — "how does X connect to Y", structural questions
- `workflow` — deployment, CI/CD, release procedures
- `tooling` — specific tool/library usage, API calls
- `convention` — naming, formatting, style questions

Each category could have different weight profiles:

```python
CATEGORY_PROFILES = {
    "debugging":    {"bm25_weight": 1.2, "tag_weight": 0.8},  # keywords matter more
    "architecture": {"bm25_weight": 0.8, "tag_weight": 1.3},  # semantic similarity matters more
    "workflow":     {"bm25_weight": 1.0, "tag_weight": 1.0},  # balanced
    "tooling":      {"bm25_weight": 1.4, "tag_weight": 0.7},  # tool names are strong keywords
}
```

### Trade-off

- Adds an LLM classification step (or lightweight keyword heuristic) per query
- May not be worth the latency for hook-triggered searches
- Consider: classify only for prompt queries (where latency budget is larger), use heuristic for tool queries

### Validation approach

- Extend the autoresearch ground truth with category labels
- Measure per-category P@1 with and without routing
- Only productionize if the per-category sweep shows meaningful variance

## Files

- `benchmark/run_search_autoresearch.py` — add per-type parameter application in `run_sweep_fast`
- `src/search/engine.py` — if productionized, add query_type parameter to `search()`
