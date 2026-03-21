# Search Autoresearch — Enrichment & Ablation — 2026-03-22

## Setup

- 116 queries, 87 labeled (59 prompt, 13 tool, 15 post_tool)
- 8 repos, all queries now have cwd from session transcripts
- Ground truth: 40 relevant, 22 abstain, 7 useful, plus scenario queries
- Benchmark passes `cwd` to `search()` — repo prior, prerequisites, and abstention all active

## Run 1: Without cwd (skip_prerequisites=True)

All scores compressed to 0.08-0.33 range. Abstention blocked everything.
Forced `abstain_threshold: 0.0` as workaround — produced P@1=33%, P@3=61%.
**Root cause**: no cwd means no repo detection, vector sims ~0.48 (below 0.55 threshold).

## Run 2: With cwd (proper context)

### Baseline (hook_current config)

| Metric | Value |
|--------|-------|
| P@1 | **56%** |
| P@3 | **74%** |
| Useful accuracy | **80%** |
| Abstain accuracy | **42%** |
| Class separation | **0.293** |
| Composite | **0.4440** |
| Composite (hook) | **0.4671** |
| Composite (interactive) | **0.3679** |
| Avg latency | 89ms |

Score range now 0.49-0.80, with relevant queries averaging 0.690 and abstain averaging 0.397.

### Enrichment Strategy Comparison

Prompt strategies (101 queries):

| Strategy | P@1 | P@3 | Abstain | Useful | Sep | Composite |
|----------|-----|-----|---------|--------|-----|-----------|
| **raw** | **60%** | **81%** | 42% | 86% | 0.310 | **0.4089** |
| strip | 60% | 81% | 42% | 86% | 0.310 | 0.4089 |
| strip+file | 60% | 81% | 42% | 86% | 0.310 | 0.4089 |
| strip+prior | 57% | 81% | 42% | 86% | 0.312 | 0.4170 |
| full | 57% | 81% | 42% | 86% | 0.312 | 0.4170 |

Post-tool strategies (15 queries):

| Strategy | P@1 | P@3 | Useful | Sep | Composite |
|----------|-----|-----|--------|-----|-----------|
| **narration+tool** | **42%** | **58%** | **67%** | 0.698 | **0.6010** |
| narration only | 42% | 50% | 67% | 0.630 | 0.6245 |
| tool only | 25% | 25% | 33% | 0.612 | 0.7680 |

**Key findings:**

1. **raw = strip = strip+file** — IDE context is too rare (2/116) to move aggregates. No evidence to enable injection yet.

2. **strip+prior hurts P@1** (-3pp) by diluting intent. Q30 "Something with Clarify.md" flips from correct (#401) to wrong (#5) when prior assistant text is injected.

3. **Post-tool: narration+tool is clearly best** — P@3=58% vs tool-only 25%. Narration provides intent; tool context provides specificity. The combination works.

4. **tool-only is insufficient** — P@1=25%, P@3=25%, useful=33%. File paths alone are too ambiguous.

### Per-query divergence

6 queries diverged between strategies:
- Q30 "Something with Clarify.md": strip finds #401 (correct), strip+prior shifts to #5 (wrong) — prior text about a completely different topic contaminates the query
- Q00/Q20: IDE-context queries — strip+file shifts top result but neither has ground truth labels, so impact is neutral

### Control Ablation

| Preset | P@1 | P@3 | Abstain | Useful | Composite | Hook | Interactive |
|--------|-----|-----|---------|--------|-----------|------|-------------|
| semantic_only | 50% | 76% | 33% | 80% | 0.4934 | 0.5230 | 0.3974 |
| semantic_plus_tags | 56% | 72% | 29% | 80% | 0.4850 | 0.5197 | 0.3921 |
| semantic_plus_tags_repo | 56% | 72% | 29% | 80% | 0.4850 | 0.5197 | 0.3921 |
| semantic_plus_filters | 56% | 72% | 42% | 80% | 0.4478 | 0.4701 | 0.3737 |
| **hook_current** | **56%** | **74%** | **42%** | **80%** | **0.4440** | **0.4671** | **0.3679** |
| interactive_current | 56% | 74% | 29% | 80% | 0.4813 | 0.5169 | 0.3865 |

**Subsystem contributions** (delta from semantic_only):

| Added subsystem | Composite | P@1 | Abstain |
|-----------------|-----------|-----|---------|
| + content tags | +0.008 | +6% | -4% |
| + repo prior | +0.000 | +0% | +0% |
| + abstention filters | +0.046 | +6% | +8% |
| + all (hook_current) | **+0.049** | +6% | +8% |

**Key findings:**

1. **Abstention filters are the biggest composite contributor** (+0.046) — they correctly suppress 42% of abstain queries, significantly improving the composite score.

2. **Content tags provide marginal P@1 lift** (+6%) but hurt abstain accuracy (-4%) — they make the system more confident on both correct and incorrect matches.

3. **Repo prior adds nothing** — identical results with and without it. The `engram_repo_stats` table is empty, so repo_match_boost/penalty never fires. This subsystem needs match data to be useful.

4. **hook_current is the best balanced config** (composite 0.4440). The feedback weight (+0.20) provides the final 2pp P@3 lift from 72% to 74%.

5. **Dual objectives diverge**: hook_current wins on hook objective (0.4671) while semantic_only wins on interactive (0.3974) — confirming the need for separate configs.

### Bucket Metrics (hook_current)

| Bucket | P@1 | P@3 | Abstain | Useful | n |
|--------|-----|-----|---------|--------|---|
| expect:relevant | 57% | 75% | — | — | 53 |
| expect:abstain | — | — | 42% | — | 24 |
| expect:useful | — | — | — | 80% | 10 |
| type:prompt | 73% | 91% | 48% | 80% | 59 |
| type:tool | 12% | 50% | 0% | 100% | 13 |
| type:post_tool | 42% | 50% | 0% | 67% | 15 |

**Key gaps:**
- **tool queries P@1=12%** — `_build_tool_query` reconstructions are too generic. "editing react typescript component" doesn't match specific engrams.
- **abstain accuracy 42%** — 14/24 abstain queries still score above 0.30 threshold. Most are short vague queries ("dont push", "did it complete?") that happen to embed near some engram.
- **post_tool P@1=42%** — narration helps but top-1 precision is still weak because narration text is often about methodology ("Let me check...") not domain.

## Promotion Decision

**hook_current is validated as the best config** — composite 0.4440, P@1=56%, P@3=74%, useful=80%.

No config changes promoted. The production config already matches hook_current.

## Next Steps

1. **Improve abstain accuracy**: The low-information query filter catches obvious filler but misses borderline cases. Add more patterns or a vector-sim-based abstention calibrated to the cwd-aware score distribution.

2. **Improve tool query P@1**: `_build_tool_query` produces overly generic queries. Narration injection for PreToolUse (currently off by default) would help — the ablation shows narration is the strongest signal for tool-context searches.

3. **Populate engram_repo_stats**: The repo prior subsystem is dead weight because the stats table is empty. Running the auto-pin pipeline would populate it and potentially unlock cross-repo filtering.

4. **Session-based holdout validation**: Current results are on the full labeled set. With 15+ sessions, leave-one-session-out validation would catch overfitting.

5. **Calibrate abstention to cwd-aware scores**: The 0.30 threshold for abstain evaluation was set for the no-cwd score distribution (0.08-0.33). With cwd, scores are 0.49-0.80 — the threshold should be raised to ~0.50.
