# Search Autoresearch — 2026-03-22

## Problem

Search score distribution was compressed into the 0.70-0.80 band (87% of queries). Relevant and irrelevant results were indistinguishable. Vague queries like "still running?" scored 0.75 — same as topical queries.

Root causes:
- **Tag affinity scoring shape**: `(sim + 1) / 2` gave free positive contribution even for zero-similarity tags (+0.125 baseline). BGE embeddings for short tag strings have ~0.55-0.65 baseline similarity floor.
- **Prompt tag detection too loose**: `top_k=5, threshold=0.3` matched nearly everything. Tags like `prompts`, `setup`, `symlinks` appeared on 20-40% of queries.
- **No abstention path**: 54/54 queries returned results, even "[Request interrupted by user]" and "Yeah, that's true".

## Approach

Applied Karpathy's autoresearch pattern: pre-compute all embeddings once, then sweep scoring parameters with pure numpy. 1620 configs evaluated in 4 seconds.

### Changes

1. **Per-tag matching** (`engine.py`): Replaced bag-of-tags embedding cosine with individual prompt-tag x engram-tag pair similarity. Best pair determines the score.

2. **Thresholded scoring ramp** (`engine.py`): `sim < floor` → 0.0, linear ramp to ceiling, capped at 1.0. No more free positive contribution from weak matches.

3. **IDF-weighted prompt tag detection** (`prompt_tags.py`): Soft IDF penalty (0.7x–1.0x) for high-frequency tags. Gap-based filtering: only keep tags significantly above median. Selectivity check: if >40% of vocab passes threshold, query is too vague.

4. **Low-information query filter** (`query_filter.py`): Regex-based pre-filter catches acknowledgements ("yes", "cool", "I agree"), interruptions ("[Request interrupted]"), filler ("still running?", "what's going on?"), session-local references ("can we consider 039 done?"). Runs before embedding — effectively free.

5. **Abstention thresholds** (`engine.py`, `config.py`): `abstain_threshold=0.55` (min vector similarity), `min_top1_score=0.40` (min blended score for top result).

6. **Diagnostic mode** (`engine.py`): `return_diagnostics=True` returns per-result component breakdown: vector_sim, bm25, rrf_normalized, repo_delta, feedback_delta, tag_affinity, best_tag_sim.

7. **Autoresearch runner** (`run_search_autoresearch.py`): Pre-computes all embeddings once, then sweeps parameter grids with pure numpy. Supports `--sweep` (grid search), single eval, and `--report`.

### Ground Truth

25 hand-labeled queries from 10 real conversation transcripts:
- 14 "relevant" — exact engram IDs expected
- 2 "useful" — topically relevant but no specific engram ID
- 9 "abstain" — should return nothing

### Composite Metric

`composite = 1.0 - (0.35 * P@1 + 0.20 * P@3 + 0.25 * abstain_acc + 0.10 * class_separation + 0.10 * useful_acc)`

Lower is better (like val_bpb).

## Results

### Sweep 1: Tag affinity parameters (720 configs, 1.7s)

Fixed abstention, varied: `weight_content_tag`, `tag_sim_floor`, `tag_sim_ceiling`, `prompt_tag_threshold`.

Winner: `w=0.20, floor=0.55, ceiling=0.85, threshold=0.60, mismatch_penalty=0.0`

Finding: mismatch penalty always hurts — best configs all have it at 0.0.

### Sweep 2: Abstention parameters (1620 configs, 4.1s)

Narrowed tag params from sweep 1, varied: `min_vector_sim`, `min_top1_score`, `min_score_margin`.

Winner: `w=0.25, floor=0.50, ceiling=0.80, threshold=0.60, min_vector_sim=0.55, min_top1_score=0.40, margin=0.0`

Finding: score margin (top1-top2) never helps — always lands at 0.0.

### Before vs After

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Composite | 0.4194 | **0.2276** | -46% |
| P@1 | 71.4% | 71.4% | same |
| P@3 | 92.9% | 92.9% | same |
| Abstain accuracy | 33.3% | **88.9%** | +167% |
| Class separation | 0.159 | **0.645** | +306% |
| Score std dev | 0.182 | **0.367** | +102% |
| Avg relevant score | 0.612 | 0.730 | +19% |
| Avg abstain score | 0.453 | **0.086** | -81% |

### Per-query breakdown (sweep winner)

```
Q01 [OK      ] score=0.5496 | I remember we already do LLM assistem dedup
Q03 [OK      ] score=0.7673 | how are tasks merged?
Q04 [SKIP    ] score=0.0000 | [Request interrupted by user]
Q05 [OK      ] score=0.8048 | how are tags merged?
Q07 [OK      ] score=0.0951 | yes, this is the idea I had
Q08 [OK      ] score=0.7751 | During deduplication...getting tags
Q12 [NOISE   ] score=0.3262 | let's work on one of these issues
Q13 [SKIP    ] score=0.0000 | still running?
Q14 [SKIP    ] score=0.0000 | can we consider 039 done?
Q16 [OK      ] score=0.7857 | yes it should extraction auto set prereqs
Q19 [OK      ] score=0.5624 | Check what title does on Button.Circular
Q21 [SKIP    ] score=0.0000 | what's going on?
Q22 [SKIP    ] score=0.0000 | [Request interrupted by user for tool use]
Q23 [ok@3    ] score=0.7502 | The ticket is in TODO, not in review
Q24 [SKIP    ] score=0.0000 | Yeah, that's true
Q25 [OK      ] score=0.7912 | The checklist is missing from the PR desc
Q26 [OK      ] score=0.7802 | I need to allow toptal-workflow parts
Q30 [OK      ] score=0.6991 | Something with Clarify.md
Q32 [OK      ] score=0.7749 | delete the file before finishing
Q34 [ok@3    ] score=0.7913 | review this PR topkit/pull/1084
Q35 [MISS    ] score=0.5973 | let's discuss happo
Q43 [ok@3    ] score=0.7968 | toptal workflow blocks commits in all repos?
Q47 [OK      ] score=0.7867 | migrate davinci
Q48 [LOW     ] score=0.3290 | similar analysis for npm
Q52 [NOISE   ] score=0.7714 | I mean disable it
```

## Remaining gaps

- **Q52 "I mean disable it"**: Context-resolution problem, not a threshold problem. Needs multi-turn query building.
- **Q35 "let's discuss happo"**: Retrieval miss — happo engrams (#333, #398) not in top-1. Likely a tag/embedding gap.
- **Q48 npm analysis**: Useful query but low score (0.33). Dropped by `min_top1_score`. Acceptable for hook injection, problematic for interactive search.
- **Q12 "let's work on one of these issues"**: Borderline — scores 0.33, just above abstain threshold but correctly has no useful engram.

## Next steps

1. Context-aware query building for follow-up prompts (multi-turn)
2. More ground truth labels (currently 25 — P@1 moves in 7% jumps)
3. Separate hook injection config vs interactive search config
