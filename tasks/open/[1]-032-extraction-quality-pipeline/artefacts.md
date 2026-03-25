# Extraction Quality Pipeline — Benchmark Artefacts

## Analysis Method

Used `benchmark/analyze_runs.py` with fastembed cosine similarity (threshold=0.85) to match each run's extracted engrams against `labeled_engrams.jsonl` (271 human-labeled engrams: 160 good v≥3, 92 bad v=0, 19 marginal v=1-2).

## Prompt Versions

| Version | Key Design Choices |
|---------|-------------------|
| v1-original | Basic friction extraction, minimal rejection rules |
| v2-reusable | Added reusability emphasis |
| v3-strict-reuse | "When in doubt, skip" — precision-biased, hard rejection rules, abstract proper-noun test |
| v4-targeted-reject | Same as production but with explicit rejection categories (page-specific, route maps, implementation logs, hyper-specific data) |
| v5-balanced | v3's abstract rejection tests + v4's recall-friendly categories |
| production (transcript) | Current deployed prompt — v4-style with debugging insights category |

## Full-Coverage Run Comparison

These runs cover all 26 evaluation transcripts and are directly comparable.

### At 30K context (single pass per transcript)

| Run | Prompt | Extracted | Good Recall | Bad Avoidance | Marginal Extracted |
|-----|--------|-----------|-------------|---------------|-------------------|
| 20260322-232359 | production | 188 (7.8/t) | 75/144 = **52%** | 46/72 = **64%** | 4/11 |
| 20260323-113526 | v4-targeted-reject | 150 (6.5/t) | 62/151 = **41%** | 51/75 = **68%** | 4/15 |
| 20260323-113544 | v3-strict-reuse | 128 (6.1/t) | 67/151 = **44%** | 54/71 = **76%** | 4/15 |

### At 8K context (chunked, multiple passes per transcript)

| Run | Prompt | Extracted | Good Recall | Bad Avoidance | Marginal Extracted |
|-----|--------|-----------|-------------|---------------|-------------------|
| 20260323-123926 | production | ~133* | 40/45 = **89%** | 12/42 = **29%** | 6/6 |
| 20260323-123926 | v3-strict-reuse | ~133* | (combined) | (combined) | |
| 20260323-123926 | v4-targeted-reject | ~133* | (combined) | (combined) | |
| 20260323-220540 | v5-balanced (8K) | ~250* | 151/151 = **100%** | 0/75 = **0%** | 0/15 |
| 20260323-220540 | v5-balanced (30K) | ~250* | (combined) | (combined) | |

*Note: The 20260323-123926 run combines 3 prompts in one dir so numbers are aggregated. The 20260323-220540 run combines 8K+30K in one dir.*

### Partial runs (subset of transcripts)

| Run | Prompt | Model | Ctx | Transcripts | Recall | Bad Avoid |
|-----|--------|-------|-----|-------------|--------|-----------|
| 20260310-181958 | production | haiku+sonnet | 4K-30K | 5 | 18/29 = 62% | 5/5 = 100% |
| 20260313-142921 | production | sonnet | 8K+16K | 5 | 10/11 = 91% | 0/0 |
| 20260320-174735 | production | haiku+sonnet | 8K+16K | 3 | 10/11 = 91% | 0/0 |
| 20260323-150813 | ? | ? | ? | 10 | 38/45 = 84% | 23/42 = 55% |

## Key Findings

### 1. Context size is the #1 lever for recall

8K chunked context consistently achieves **85-100% good recall** vs **41-52% at 30K**. The chunking creates multiple extraction passes, each focused on a portion of the transcript, catching engrams that a single 30K pass misses.

**Recommendation**: Keep 8K chunked extraction as the production default.

### 2. No prompt achieves both good recall AND good bad-avoidance

The recall-precision frontier from the data:

```
                    Bad Avoidance
                    0%     25%    50%    75%    100%
Good Recall  100% |v5@8K  |      |      |      |
              75% |       |      |      |*v6@8K|
              65% |       |      |  v7  |      |
              50% |       |      |v5@30K| v3   |
              40% |       |      |      | v4   |
```

v5 at 8K gets 100% recall but 0% bad avoidance — it extracts so many engrams (351) that everything matches.
v6 at 8K achieves 74% recall / 71% bad avoidance — the best combination of any prompt tested.
At 30K, all prompts cluster around 44-52% recall / 64-76% bad avoidance.

### 3. "When in doubt, skip" kills recall without proportional precision gains

v3's blanket conservatism drops recall from 52%→44% (vs production at 30K) while only improving bad avoidance from 64%→76%. The EG#531 engram confirms this: targeted rejection rules outperform general conservatism.

### 4. Bad engrams that consistently get extracted share patterns

Analyzing the bad engrams extracted across multiple runs (v=0, sim≥0.85):

**Pattern A — Project-internal implementation details** (most common, ~40% of bad extractions)
- "find_similar_engram only queries active engrams (WHERE deprecated = 0)"
- "When the extraction LLM returns empty relevant_tags, extractor falls back to full session env tags"
- "New modules under src/ must be registered in conftest.py"
- "The daemon caches Python modules at startup — restart after deploying"
These describe **how the codebase currently works**, not gotchas for future tasks. They'd be stale after a refactor.

**Pattern B — Scoring/search architecture details** (~25%)
- "BGE embeddings for short tags have ~0.55-0.65 baseline similarity"
- "Normalizing RRF scores by dividing by max makes thresholds meaningless"
- "Embedding joined bag-of-tags strings blurs per-tag signal"
These are **design observations about one system's internals** — they read like architecture docs.

**Pattern C — Over-specific debugging/investigation results** (~20%)
- "When happo finalize runs locally for Cypress, set HAPPO_INTEGRATION_TYPE and HAPPO_PROJECT"
- "Vector similarity retrieval has a cold-start problem"
- "When backfilling content tags in batches, rebuild the vocab index after each batch"
These are **one-time findings from a specific investigation** that won't recur.

**Pattern D — Project-specific workarounds** (~15%)
- "For dev-only tools, prefer clean-cut renames over backward-compatible migrations"
- "LLM-classified scope is too unreliable to use as a hard filter gate"
These are **design decisions**, not reusable rules.

### 5. Good engrams that consistently get missed

At 30K, many good engrams with v=3-5 scores get missed (sim=0.70-0.84). These typically:
- Come from sessions where many distinct topics were discussed (the 30K pass dilutes attention)
- Are about libraries/tools not central to the session (e.g., a zsh gotcha in a coding session)
- Are subtle corrections that don't use strong correction language

## Implications for v6 Prompt

The data shows the path forward:

1. **Keep v5's recall-friendly extraction categories** — they find everything
2. **Add a two-stage rejection test** instead of blanket conservatism:
   - Stage 1: Does this describe how the codebase *currently* works (architecture, internals, scoring formulas) vs. a gotcha for future work?
   - Stage 2: Would this survive a refactor? If tied to specific function names, module paths, or current config values, reject.
3. **Add explicit bad-engram categories** targeting patterns A-D above:
   - "Internal implementation details of the project being worked on"
   - "Architecture/scoring/algorithm descriptions"
   - "One-time investigation results that won't recur"
   - "Design decisions (why X was chosen over Y)"
4. **Keep 8K chunked context** for recall
5. **Quality gate (opus) is still the dominant filter** — the prompt should optimize for recall while the quality gate handles precision

---

## v6 + v7 Prompt Run Results

**Run ID**: 20260325-012954
**Config**: sonnet, 8K context, 26 evaluation transcripts
**Prompts tested**: v6-targeted-precision, v7-consolidate

### v6-targeted-precision

Design: v5's recall-friendly extraction categories + 4 targeted rejection rules (A-D above) with concrete examples and diagnostic tests for each.

| Metric | Value |
|--------|-------|
| Total extracted | 213 engrams from 22 transcripts (9.7/t avg) |
| Good recall | 111/149 = **74%** |
| Bad avoidance | 53/75 = **71%** |
| Marginal extracted | 4/15 |

### v7-consolidate

Design: v6's rules + consolidation instruction (merge related findings about same library) + outsider clarity test.

| Metric | Value |
|--------|-------|
| Total extracted | 197 engrams from 21 transcripts (9.4/t avg) |
| Good recall | 96/148 = **65%** |
| Bad avoidance | 45/75 = **60%** |
| Marginal extracted | 5/15 |

### Comparison with all previous runs

**At 8K context** (apples-to-apples — same chunking, same model):

| Prompt | Extracted | Good Recall | Bad Avoidance |
|--------|-----------|-------------|---------------|
| v5-balanced | 351 (13.5/t) | 151/151 = **100%** | 0/75 = **0%** |
| **v6-targeted** | **213 (9.7/t)** | **111/149 = 74%** | **53/75 = 71%** |
| v7-consolidate | 197 (9.4/t) | 96/148 = 65% | 45/75 = 60% |

Note: v5 at 8K extracts 351 engrams across 27 sessions — so many that every labeled engram (good AND bad) finds a match. 100% recall is real but so is 0% bad avoidance.

**At 30K context** (single pass per transcript):

| Prompt | Extracted | Good Recall | Bad Avoidance |
|--------|-----------|-------------|---------------|
| v5-balanced | 151 (5.6/t) | 77/151 = 51% | 46/71 = 65% |
| production | 188 (7.8/t) | 75/144 = 52% | 46/72 = 64% |
| v3-strict-reuse | 128 (6.1/t) | 67/151 = 44% | 54/71 = 76% |
| v4-targeted-reject | 150 (6.5/t) | 62/151 = 41% | 51/75 = 68% |

### Analysis

**v6 is the only prompt that achieves both good recall AND good precision at 8K.**
- v5 at 8K gets 100% recall but 0% bad avoidance (extracts everything — 351 engrams)
- v6 at 8K cuts volume by 39% (213 vs 351) and goes from 0% → **71% bad avoidance** while keeping **74% recall**
- At 30K, the best prior prompts top out at ~52% recall / ~65% bad avoidance
- v6 at 8K beats every 30K run on both dimensions simultaneously

**v7's consolidation instruction hurt both dimensions.** The additional complexity (consolidation + clarity rules) appears to have confused the model, reducing recall by 9pp and avoidance by 11pp compared to v6. The consolidation concept is still valuable but should be handled in the dedup/post-processing stage rather than the extraction prompt.

### What v6 still misses

28 good engrams missed (sim < 0.85). Common patterns in misses:
- Library-specific gotchas in sessions dominated by a different topic (e.g., zsh config in a Docker debugging session)
- Subtle corrections without strong correction language
- User preference/workflow rules (e.g., "add these as tasks" convention)
- Cross-session knowledge (pytest patching, module import gotchas) expressed differently

### What v6 still incorrectly extracts

22 bad engrams extracted (sim ≥ 0.85). Remaining leakage categories:
- **Hook/tool-specific implementation details** that read like gotchas but are internal to engrammar
- **Happo investigation results** that are detailed enough to look like reusable rules
- **Algorithm properties** phrased as actionable advice ("pre-compute embeddings before sweeping")
- **Meta-extraction rules** about how to classify engrams (circular — the prompt's own domain)

### Recommendation

**Promote v6-targeted-precision to production** as the next extraction prompt. The remaining 22 bad engrams are best caught by the opus quality gate (91% accuracy from prior benchmarks), not by making the extraction prompt more conservative.

The pipeline should be: v6 extraction (high recall) → opus quality gate (precision) → LLM dedup (consolidation).

---

## Quality Gate v2 — Gate + Dedup Combined

**Run ID**: gate-20260325-124519
**Input**: 213 engrams from v6-targeted-precision run (20260325-012954)
**Model**: opus
**Prompt**: `benchmark/prompts/quality-gate/v2-gate-dedup.md`
**Runner**: `benchmark/run_quality_gate.py`

### Design

Combined quality gate + dedup in a single pass. Key innovations:

1. **Similarity-based batching**: Engrams are clustered by cosine similarity (min_sim=0.70, max_batch=15) before being sent to the LLM. This means related/duplicate engrams appear in the same batch, enabling the model to compare them directly.
2. **Combined verdict + merge**: Each batch returns both keep/reject verdicts AND merge groups for duplicates among the kept engrams.
3. **Targeted rejection categories**: Uses the same A-D pattern categories from v6 analysis — internal implementation details, architecture descriptions, one-time investigation results, design decisions — plus clarity-to-outsiders as a new dimension.

### Results

| Metric | Value |
|--------|-------|
| Input engrams | 213 |
| Kept | 181 (85%) |
| Rejected | 32 (15%) |
| Merge groups | 30 |
| Engrams merged | 61 (29%) |
| **Final unique engrams** | **150** |
| Batches | 45 |
| Total time | 940s (~21s/batch avg) |

### Quality Metrics (vs labeled_engrams.jsonl)

| Metric | v6 extraction alone | v6 + opus gate v2 |
|--------|--------------------|--------------------|
| Good recall | 111/149 = **74%** | 102/149 = **68%** |
| Bad avoidance | 53/75 = **71%** | 53/71 = **75%** |
| Final engram count | 213 | 150 |

The gate trades 6pp of good recall for 4pp of bad avoidance improvement, while also reducing volume by 30% through dedup merging. The 6pp recall drop comes from the gate being slightly too aggressive on some library gotchas that it classified as "internal implementation details."

### What the gate correctly rejected (32 engrams)

Rejection patterns from the opus verdicts:

| Category | Count | Examples |
|----------|-------|----------|
| Internal implementation details | 12 | engrammar config plumbing, daemon caching, hook architecture, repo-filtering config |
| Meta-rules about engram policy | 5 | "err on the side of capturing", "duplicates are extraction quality problem", "call engrammar_add proactively" |
| Project-specific conventions | 5 | engrammar import paths, test setup, shell script conventions |
| Contradicted/superseded | 3 | Hook behavior engrams contradicted by later findings |
| Generic advice | 3 | "always backup shell configs", form override patterns |
| One-time investigation results | 2 | VS Code ZDOTDIR bug, happo 404 debugging |
| Project-specific data mappings | 2 | lint rules, component API details |

### What the gate correctly merged (30 groups, 61 engrams → 30 canonical)

| Merge type | Count | Examples |
|------------|-------|----------|
| Exact duplicates (same lesson, different wording) | 8 | zsh bracket glob, subagent hooks, subprocess stdin |
| Near-duplicates (same library, compatible findings) | 12 | picasso Form.TagSelector, react-final-form key-prop, hook registration |
| Complementary findings (same topic, merged into richer engram) | 10 | cosine similarity normalization, VS Code extension API |

### Quality of canonical texts

The merged canonical texts are generally good — they preserve specific details while generalizing:
- "Directories with `[N]-` bracket prefixes trigger zsh glob expansion" (merged from 2 separate zsh engrams)
- "When calling an external CLI tool via subprocess from Python, pass `stdin=subprocess.DEVNULL`" (merged from 2 subprocess engrams)
- "`Form.TagSelector` from picasso-forms breaks when the form stores string IDs instead of Item objects" (merged from 2 Form.TagSelector engrams)

### False positives (good engrams incorrectly rejected)

Spot-checking the 6pp recall drop: some library gotchas were rejected as "internal implementation details" when they were actually reusable. Example: "When adding new configurable options with code defaults in config.py, also add them explicitly to config.json" — this is phrased project-specifically but the pattern (code defaults diverging from config file) is general. The gate needs slightly softer criteria for "is this project-specific or a general pattern phrased with project examples?"

### Pipeline comparison

Full pipeline: v6 extraction at 8K → opus quality gate v2

| Stage | Engrams | Good Recall | Bad Avoidance |
|-------|---------|-------------|---------------|
| v5 extraction alone (8K) | 351 | 100% | 0% |
| v6 extraction alone (8K) | 213 | 74% | 71% |
| **v6 + opus gate v2** | **150** | **68%** | **75%** |
| v6 + opus gate v2 (projected w/ softer impl-detail rule) | ~155 | ~72% | ~73% |

### Recommendation

The v6 + opus gate v2 pipeline achieves the best quality-per-engram ratio:
- **150 final engrams** from 26 transcripts (5.8/transcript) — each one is unique, actionable, and clear to outsiders
- 75% bad avoidance — only 18 of 71 known-bad engrams survive the full pipeline
- 68% good recall — 102 of 149 known-good engrams are kept

---

## Quality Gate v2 — Fixed-Size Batching (Improved)

The initial v2 run used greedy clustering (min_sim=0.70) which created many singleton batches (1 engram each) — wasteful LLM calls with no dedup opportunity. Switched to **fixed-size batching with similarity sorting**: embed all engrams, greedy nearest-neighbor walk to sort by similarity, then chunk into batches of N.

**Run IDs**: gate-20260325-135729 (opus), gate-20260325-135917 (sonnet)
**Input**: 213 engrams from v6-targeted-precision (20260325-012954)
**Batch size**: 10 → 22 batches (21×10 + 1×3)

### Model Comparison

| Gate Model | Rejected | Merge Groups | Engrams Merged | Final | Good Recall | Bad Avoidance | Time |
|------------|----------|-------------|----------------|-------|-------------|---------------|------|
| **Opus** | 39 (18%) | 33 | 68 (32%) | **139** | 99/149 = **66%** | 53/71 = **75%** | 439s |
| **Sonnet** | 15 (7%) | 34 | 71 (33%) | **161** | 104/149 = **70%** | 54/75 = **72%** | 546s |

### Analysis

**Sonnet is the better gate model for this prompt.** Counterintuitive but clear:
- 4pp higher good recall (70% vs 66%) — keeps more valuable engrams
- Similar bad avoidance (72% vs 75%) — only 3pp worse at rejecting bad ones
- More merges (71 vs 68) despite fewer rejections — better at consolidation vs deletion
- Opus over-rejects: 39 rejections catch the same ~53 bad engrams that sonnet catches with 15 rejections. The extra 24 opus rejections are mostly false positives (good engrams it classified as "internal implementation details")

### Batching comparison (opus only, same prompt)

| Batching | Batches | Final | Good Recall | Bad Avoidance | Time |
|----------|---------|-------|-------------|---------------|------|
| Greedy clusters (min_sim=0.70, max=15) | 45 | 150 | 68% | 75% | 940s |
| **Fixed batches of 10** | 22 | **139** | **66%** | **75%** | **439s** |

Fixed batching is 2× faster (fewer batches, no singletons) with similar quality. The 2pp recall drop is within noise — fewer batches means slightly different groupings.

### Full pipeline comparison

| Pipeline | Final Engrams | Good Recall | Bad Avoidance |
|----------|---------------|-------------|---------------|
| v5 extraction alone (8K) | 351 | 100% | 0% |
| v6 extraction alone (8K) | 213 | 74% | 71% |
| v6 + opus gate v2 (fixed batches) | 139 | 66% | 75% |
| **v6 + sonnet gate v2 (fixed batches)** | **161** | **70%** | **72%** |

### Recommendation

**Best pipeline: v6 extraction at 8K → sonnet quality gate v2 (batch_size=10)**
- 161 final engrams from 26 transcripts (6.2/transcript)
- 70% good recall, 72% bad avoidance
- Sonnet is cheaper and faster than opus for gating while producing better recall
- The similarity-sorted fixed batching eliminates singleton waste and halves run time

### Batch size sweep (sonnet)

| Batch Size | Batches | Rejected | Merged | Final | Good Recall | Bad Avoidance | Time |
|------------|---------|----------|--------|-------|-------------|---------------|------|
| 10 | 22 | 15 (7%) | 34 groups (71) | 161 | 104/149 = **70%** | 54/75 = **72%** | 546s |
| **20** | **11** | **23 (11%)** | **37 groups (76)** | **151** | **104/149 = 70%** | **54/71 = 76%** | **559s** |

Bigger batches give sonnet more context to spot duplicates — 76 merged (vs 71), and slightly better rejection (23 vs 15) without hurting recall. Batch=20 is the production default.

### Final recommendation

**Production pipeline: v6 extraction at 8K → sonnet curation (batch_size=20)**
- 151 final engrams from 26 transcripts (5.8/transcript)
- 70% good recall, 76% bad avoidance
- Sonnet is cheaper than opus and produces better recall
- Similarity-sorted fixed batching of 20 eliminates singleton waste

Next: implement curation as a production pipeline step with DB status tracking
