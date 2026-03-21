# Search Autoresearch — Enrichment & Ablation — 2026-03-22

## Setup

- 116 queries, 87 labeled (59 prompt, 13 tool, 15 post_tool)
- 8 repos (staff-portal 34, engrammar 17, talent-activation-frontend 4, sourcing-extension 4, via-dacica 4, toptal 3, screening-wizard-frontend 2, topkit 1)
- Ground truth: 40 relevant, 22 abstain, 7 useful, plus 15 scenario queries testing repo filtering
- Benchmark uses `skip_prerequisites=True` (no cwd/repo context)

## Enrichment Strategy Comparison

Strategies tested on prompt queries (101 queries after excluding post_tool):

| Strategy | P@1 | P@3 | Abstain | Useful | Sep | Composite |
|----------|-----|-----|---------|--------|-----|-----------|
| raw | 38% | 67% | 71% | 0% | 0.107 | 0.5455 |
| strip | 38% | 67% | 71% | 0% | 0.107 | 0.5455 |
| strip+file | 38% | 67% | 71% | 0% | 0.107 | 0.5455 |
| strip+prior | 36% | 64% | 71% | 0% | 0.109 | 0.5585 |
| full | 36% | 64% | 71% | 0% | 0.109 | 0.5585 |

Post-tool strategies (15 queries):

| Strategy | P@1 | P@3 | Useful | Sep | Composite |
|----------|-----|-----|--------|-----|-----------|
| narration+tool | 8% | 58% | 33% | 0.251 | 0.7957 |
| narration only | 17% | 42% | 33% | 0.256 | 0.7994 |
| tool only | 25% | 33% | 0% | 0.288 | 0.8171 |

### Key Findings

1. **raw = strip for all practical purposes.** Only 2 queries have IDE tags, so stripping has near-zero aggregate impact. The tag content is short enough that it doesn't meaningfully shift embeddings.

2. **strip+prior slightly hurts P@1** (-2pp) by injecting prior assistant text that shifts the embedding away from the query's core intent. 4 queries diverged — in 3 cases the prior context pushed the top result to a wrong engram.

3. **Post-tool: narration+tool has best P@3 (58%)** — narration provides the intent signal that makes tool context useful. Tool-only has better P@1 (25%) but much worse P@3 (33%) — it's a sharper but narrower signal.

4. **Post-tool: narration-only has best P@1** among narration strategies (17%) — the narration alone is often a better search query than the combined narration+tool text, because tool context (file paths) can dilute the semantic signal.

### Remaining Issue

Useful accuracy is 0% across all prompt strategies — queries labeled "useful" score below the 0.40 threshold because the benchmark runs without cwd context, producing compressed scores in the 0.08-0.33 range.

## Control Ablation

6 presets from `semantic_only` to `hook_current`, measuring incremental subsystem contribution:

| Preset | P@1 | P@3 | Abstain | Useful | Composite | Hook | Interactive |
|--------|-----|-----|---------|--------|-----------|------|-------------|
| semantic_only | 0% | 52% | 100% | 10% | 0.6339 | 0.5598 | 0.7170 |
| semantic_plus_tags | 30% | 63% | 75% | 10% | **0.5628** | **0.5341** | 0.6270 |
| semantic_plus_tags_repo | 30% | 63% | 75% | 10% | 0.5628 | 0.5341 | 0.6270 |
| semantic_plus_filters | 0% | 0% | 100% | 0% | 0.7500 | 0.6500 | 0.9000 |
| hook_current | 0% | 0% | 100% | 0% | 0.7500 | 0.6500 | 0.9000 |
| interactive_current | 33% | 61% | 71% | 10% | 0.5639 | 0.5403 | **0.6274** |

### Subsystem Contributions (delta from semantic_only)

| Added subsystem | Composite | P@1 | Abstain |
|-----------------|-----------|-----|---------|
| + content tags | **+0.071** | **+30%** | -25% |
| + repo prior | +0.000 | +0% | +0% |
| + abstention filters | -0.116 | +0% | +0% |
| + all (hook_current) | -0.116 | +0% | +0% |

### Key Findings

1. **Content tag affinity is the single biggest contributor** — +0.071 composite improvement, +30% P@1. This validates the per-tag matching approach from the previous autoresearch.

2. **Repo prior adds zero value** in the benchmark context. This is because `skip_prerequisites=True` means no cwd is detected, so repo_match_boost/penalty never fires. In production (with cwd), it would help.

3. **Abstention filters are too aggressive** for the benchmark context — they block all queries because vector similarities without cwd are below the 0.55 threshold. `semantic_plus_filters` and `hook_current` both show 0% P@1.

4. **`interactive_current` is the best overall config** (composite 0.5639) — it keeps tags and repo prior but disables abstention, which is correct for the benchmark's no-cwd context.

5. **Hook vs Interactive objectives diverge clearly**: semantic_only wins on hook objective (abstain=100%) but is worst on interactive (no P@1). interactive_current is best overall balanced.

## Baseline Single Eval

Current production config with abstention disabled:

| Metric | Value |
|--------|-------|
| P@1 | 33% |
| P@3 | 61% |
| Useful accuracy | 10% |
| Abstain accuracy | 71% |
| Class separation | 0.101 |
| Composite | 0.5639 |
| Avg latency | 57ms |

### Score Distribution

- Relevant queries: avg score 0.278
- Abstain queries: avg score 0.177
- Score range: 0.08 to 0.78 (most in 0.23-0.33)
- Only 1 query above 0.50 (Q86 "TODO comments" at 0.779)

## Next Steps

1. **The benchmark needs cwd context.** Without it, repo prior and abstention can't be evaluated. Add `cwd` field to search_queries.json based on session transcript paths, and pass it to `search()`.

2. **Enrichment has minimal impact with current data.** Only 2/116 queries have IDE context. To properly evaluate enrichment, either:
   - Collect more sessions from IDE (VS Code) where IDE tags are present
   - Or inject synthetic IDE context for a subset of queries

3. **Post-tool narration is valuable but undertested.** 15 post_tool queries show narration+tool giving the best P@3. More real PostToolUse events from diverse repos would strengthen this.

4. **Content tags are the proven winner.** Future sweeps should focus on tag affinity parameters (already optimized in previous autoresearch) rather than trying to squeeze more from enrichment.

5. **Hook vs interactive configs should be separate.** The abstention thresholds that work for hook injection (high min_score, aggressive filtering) are catastrophic for interactive search. Ship two configs.
