# Task: BM25 Token Overlap as Abstention Signal

- Priority: Medium
- Complexity: C1
- Status: Open

## Problem

Abstain accuracy is 50% at production settings (65% with sweep winner). The current abstention relies on:
1. Regex query filter (catches syntactic patterns like "sounds good")
2. `abstain_threshold` on raw vector similarity
3. `min_top1_score` on final blended score

These miss semantically vague queries where vector similarity is deceptively high (BGE baseline ~0.55-0.65 even for unrelated text). Example: "it's in staff-portal" passes regex, gets vector sim ~0.62 (noise range), and produces irrelevant results.

## Proposed approach

Use BM25 token overlap ratio as an orthogonal abstention signal:

```python
# For each query, compute what fraction of query tokens appear in top BM25 result
query_tokens = set(tokenize(query))
best_bm25_tokens = set(tokenize(top_bm25_result["text"]))
token_overlap = len(query_tokens & best_bm25_tokens) / max(len(query_tokens), 1)
```

Abstain when **both** vector_sim and token_overlap are below their respective thresholds. This catches queries that are neither semantically nor lexically close to any engram.

### Why this helps

- Orthogonal to vector similarity — catches different failure modes
- "it's in staff-portal" has low token overlap (only "staff-portal" might match, common words filtered)
- Legitimate queries like "happo finalize failing" have high token overlap even if vector sim is moderate
- Very cheap to compute — BM25 tokenization is already done

## Autoresearch testing

Pre-compute `max_token_overlap` per query in `PrecomputedData` (fraction of query tokens found in top BM25 result). Add to sweep grid:

```python
"min_token_overlap": [0.0, 0.1, 0.2, 0.3]
```

Abstain when `best_vector_sim < min_vector_sim AND token_overlap < min_token_overlap`. The AND condition prevents over-abstaining — either strong signal is enough to proceed.

## Expected impact

+5-10% abstain accuracy by combining two orthogonal signals. Risk: over-abstaining on queries with novel vocabulary not in any engram.

## Relation to other ideas

- Complements `similarity-floor-threshold.md` (which focuses on vector-only floor)
- Could be combined with `min_vector_sim` in a single compound abstention gate

## Files

- `benchmark/run_search_autoresearch.py` — pre-compute overlap in `PrecomputedData`, add to sweep
- `src/search/engine.py` — if productionized, add overlap check near abstention logic (step 2.5)
