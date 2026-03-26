# Evaluation Pipeline Status

## Summary

We've implemented weighted sigmoid attribution for evaluation feedback and set up an autoresearch pipeline to optimize tag relevance scoring. This work spans **#016** (adaptive evaluation context) and **#030** (weighted tag attribution).

## What Changed

### 1. Data Flow — Store Context at Evaluation Time

**Modified files:**
- `src/infra/db.py` — Added `prompt_tags`, `query_text`, and `engram_context` columns to `session_shown_engrams`
- `hooks/on_prompt_start.py`, `hooks/on_tool_use.py`, `hooks/on_session_stop.py` — Pass prompt tags when recording shown engrams

**New schema:**
```sql
ALTER TABLE session_shown_engrams ADD COLUMN prompt_tags TEXT;
ALTER TABLE session_shown_engrams ADD COLUMN query_text TEXT;
ALTER TABLE session_audit ADD COLUMN engram_context TEXT; -- JSON: {tag_sims: {tag: sim, ...}}
```

This lets the evaluator know which prompt tags were active when each engram was shown, enabling precise attribution.

### 2. Attribution Logic — Shifted Sigmoid Weighting

**Modified files:**
- `src/infra/evaluator.py` — Implemented `shifted_sigmoid_weight()` and weighted attribution

**Formula:**
```
tag_sim < 0.20 → weight = 0.0       (below floor, no signal)
0.20 ≤ sim < 0.80 → weight = ((sim - 0.20) / 0.60)²  (quadratic ramp)
tag_sim ≥ 0.80 → weight = 1.0       (above ceiling, full signal)

attribution_score = eval_verdict × weight
```

**Behavior:**
- Tag at sim 0.95 gets ~88% of eval signal
- Tag at sim 0.60 gets ~25% of eval signal
- Tag at sim 0.40 gets ~6% of eval signal
- Tag at sim below 0.20 gets 0% (not attributed)

This concentrates signal on tags that actually matched the query.

### 3. Evaluation Autoresearch Pipeline

**New files:**
- `benchmark/eval_attribution_comparison.py` — Analyzes signal distribution under old vs new attribution
- `benchmark/eval_sweep_config.yaml` — Autoresearch sweep config for attribution hyperparameters

**Hyperparameters to sweep:**
- `attribution_floor` — min tag similarity to receive signal (values: 0.10, 0.15, 0.20, 0.25, 0.30)
- `attribution_ceiling` — similarity above which weight saturates (values: 0.60, 0.70, 0.80, 0.90)
- `weighting_curve` — attribution weight curve (linear, quadratic, cubic)
- `feedback_dampening` — reduce boost amplitude for low-eval rows (0.2-0.5)
- `filter_threshold` — MIN_EVALS_FOR_FILTER (1, 2, 3, 4)

## Baseline Analysis

Ran `eval_attribution_comparison.py` on current DB (2026-03-26):

### Signal Distribution
| Eval count | Tags with count | Total pos evals | Total neg evals |
|---|---|---|---|
| 1 | 1680 | 1455 | 225 |
| 2 | 619 | 998 | 240 |
| 3+ | 1437 | 5638+ | 1200+ |

**Key insight:** 1680 tags (40% of corpus) have only 1 evaluation. These are the most at-risk for false negative filtering, but also where weighted attribution has most impact.

### Top Tags by Signal
1. `repo:engrammar` — 82.5 total signal (2046 pos, 338 neg evals)
2. `python` — 70.1 total signal (1426 pos, 128 neg evals)
3. `github` — 47.2 total signal (1042 pos, 100 neg evals)
4. `testing` — 41.0 total signal (818 pos, 92 neg evals)
5. `repo:staff-portal` — 38.5 total signal (680 pos, 66 neg evals)

### Recovery & Filter Threshold Analysis
- **Negatively-scored tags:** 401 total
- **Had at least 1 positive eval:** 140 (35% recovery potential)
- **Had at least 2 positive evals:** 68 (17%)

**Implication:**
- **Filter at threshold=1** → Risky, 140 tags would be filtered on first negative and likely recover later (~35% false-positive removal)
- **Filter at threshold=2** → Safer, 42 additional early filters with lower recovery rate
- **Filter at threshold=3** → Current conservative approach, but blocks signal for 1-2 eval rows

## Next Steps

### Phase 1: Deploy & Baseline (now)
- [ ] Deploy code to ~/.engrammar with new schema
- [ ] Run benchmark with old (simple avg) vs new (weighted sigmoid) attribution
- [ ] Measure: signal concentration on matched tags, per-tag accuracy improvement

### Phase 2: Autoresearch Sweep (next)
- [ ] Run eval_sweep with 5 variable dimensions (100+ configs)
- [ ] Metric: tag_relevance_precision (% of per-tag evals matching expected direction)
- [ ] Identify optimal floor, ceiling, curve, filter threshold
- [ ] Measure secondary metrics: signal_concentration, recovery_rate

### Phase 3: Evaluation Context Optimization (#016)
- [ ] Implement local transcript windows (3 turns before/after engram shown)
- [ ] Measure evaluator output quality improvement
- [ ] A/B: head+tail vs local window vs full transcript

### Phase 4: Closed-Loop Feedback
- [ ] Track which engrams have highest eval variance (disagreement)
- [ ] Feed high-variance engrams to extraction rewrite pipeline
- [ ] Measure: extraction prompt improves variance on retry

## Impact on Search Pipeline

The weighted attribution feeds into search ranking via:

```
search → show engrams with tag_sims → evaluation → engram_tag_relevance with weights
                                                            ↓
                                    (downstream) boost by relevance_delta
```

**Current:** Simple avg feedback_delta = (avg_score / 3.0) * RELEVANCE_WEIGHT
**New:** Per-tag attribution means tags that matched the query get stronger feedback signal, unmatched tags get none

This should improve search quality because:
1. **Tag affinity boost** gets stronger signal on relevant tags
2. **False negatives filter** removes noisy engrams faster
3. **Signal concentration** prevents one-off negative evals from tainting whole engram

## Files Reference

| File | Purpose |
|---|---|
| `src/infra/db.py` | Schema + migration for context storage |
| `src/infra/evaluator.py` | Shifted sigmoid attribution logic |
| `hooks/on_{prompt_start,tool_use,session_stop}.py` | Tag capture + context recording |
| `benchmark/eval_attribution_comparison.py` | Analysis + visualization |
| `benchmark/eval_sweep_config.yaml` | Autoresearch sweep specification |
| `tasks/open/[2]-016-adaptive-evaluation-transcript-context/` | Task writeup |
| `tasks/completed/[1]-030-weighted-tag-attribution-evaluation/` | Task completion |

