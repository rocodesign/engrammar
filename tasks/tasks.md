# Engrammar — Tasks

This file is the index. Detailed task writeups live under `tasks/`.

## How Tasks Are Organized

- Open tasks live in `tasks/open/`, one folder per task.
- Completed tasks live in `tasks/completed/`.
- Each task has its own folder: `tasks/open/[priority]-NNN-slug/task.md` (or `tasks/completed/[priority]-NNN-slug/task.md` once done)
- Folder names use a priority prefix:
  - `[1]-...` = High
  - `[2]-...` = Medium
  - `[3]-...` = Low
- Future ideas live in `tasks/ideas/`

## Priority Scale

- **High `[1]`** — blocks other work or degrades core functionality
- **Medium `[2]`** — improves quality but system works without it
- **Low `[3]`** — nice to have

## Complexity Scale

- `C1` = low complexity (low-hanging)
- `C2` = medium complexity
- `C3` = high complexity

## Open Tasks

### High

- [ ] **#018 Normalize and blend scoring with configurable weights** `C2`
  - `tasks/open/[1]-018-widen-tag-penalty/task.md`
- [x] **#019 Lower tag relevance evidence threshold** `C1` `won't-fix: threshold is correct`
  - `tasks/completed/[1]-019-lower-tag-evidence-threshold/task.md`
- [x] **#030 Weighted tag attribution for evaluation** `C2`
  - `tasks/completed/[1]-030-weighted-tag-attribution-evaluation/task.md`
- [x] **#031 Preserve evaluation context through dedup merges** `C1`
  - `tasks/completed/[1]-031-preserve-evaluation-context-through-dedup/task.md`
- [ ] **#032 Extraction quality pipeline — consolidation, generalization, clarity** `C3`
  - `tasks/open/[1]-032-extraction-quality-pipeline/task.md`

### Medium

- [ ] **#005 Incremental embedding index update** `C2`
  - `tasks/open/[2]-005-incremental-embedding-index/task.md`
- [ ] **#009 Richer tool-use context for PreToolUse search** `C2`
  - `tasks/open/[2]-009-richer-tool-use-context/task.md`
- [ ] **#010 Promote engrams to generic when useful across repos** `C2`
  - `tasks/open/[2]-010-tag-generalization/task.md`
- [ ] **#012 Stage auto-extracted engrams before injection** `C3`
  - `tasks/open/[2]-012-stage-auto-extracted-engrams/task.md`
- [ ] **#015 Daemon priority queue with background dedup** `C2`
  - `tasks/open/[2]-015-daemon-priority-queue/task.md`
- [ ] **#016 Adaptive transcript context for evaluation** `C2`
  - `tasks/open/[2]-016-adaptive-evaluation-transcript-context/task.md`
- [ ] **#022 Add session observational memory layer** `C3`
  - `tasks/open/[2]-022-session-observational-memory/task.md`

- [ ] **#024 Query-type-aware scoring profiles** `C2`
  - `tasks/open/[2]-024-query-type-scoring-profiles/task.md`
- [ ] **#025 Multi-tag match count for reranking** `C1`
  - `tasks/open/[2]-025-multi-tag-match-reranking/task.md`
- [ ] **#026 BM25 token overlap as abstention signal** `C1`
  - `tasks/open/[2]-026-bm25-overlap-abstention/task.md`
- [ ] **#027 Dedup precision/recall benchmark** `C2`
  - `tasks/open/[2]-027-dedup-precision-recall-benchmark/task.md`
- [ ] **#028 Semantic cluster deduplication** `C3`
  - `tasks/open/[2]-028-semantic-cluster-dedup/task.md`
- [ ] **#039 Failure-driven engram evolution** `C3` `depends-on: #012, #031`
  - `tasks/open/[2]-039-failure-driven-engram-evolution/task.md`
- [ ] **#040 Engram versioning for evaluation integrity** `C2`
  - `tasks/open/[2]-040-engram-versioning-evaluation-integrity/task.md`

### Low

- [ ] **#013 Batch processing for extracted engrams** `C2`
  - `tasks/open/[3]-013-batch-extracted-engram-processing/task.md`
- [ ] **#014 Add extraction pipeline observability** `C1`
  - `tasks/open/[3]-014-extraction-pipeline-observability/task.md`
- [ ] **#041 Robust LLM output parsing with fallback strategies** `C1`
  - `tasks/open/[3]-041-robust-llm-output-parsing/task.md`

## Completed Tasks

### High

- [x] **#001 Fix self-extraction fake session IDs** `C1`
  - `tasks/completed/[1]-001-self-extraction-fake-session-ids/task.md`
- [x] **#006 Deduplicate lesson injection globally per session** `C1`
  - `tasks/completed/[1]-006-dedup-lessons-per-session/task.md`
- [x] **#007 Per-turn extraction via Stop hook** `C2`
  - `tasks/completed/[1]-007-session-end-extraction/task.md`
- [x] **#011 Coalesce queued turn extraction requests** `C2`
  - `tasks/completed/[1]-011-coalesced-turn-extraction-queue/task.md`
- [x] **#017 Add minimum score threshold for prompt search** `C1`
  - `tasks/completed/[1]-017-reduce-injection-noise/task.md`
- [x] **#020 Prompt-derived content tag affinity** `C2`
  - `tasks/completed/[1]-020-prompt-derived-tags/task.md`
- [x] **#021 LLM-selected relevant tags during extraction** `C2`
  - `tasks/completed/[1]-021-extraction-relevant-tags/task.md`

### Medium

- [x] **#002 Fix extraction prompt wrong categories** `C1`
  - `tasks/completed/[2]-002-extraction-wrong-categories/task.md`
- [x] **#003 LLM-assisted engram deduplication** `C2`
  - `tasks/completed/[2]-003-lesson-dedup-too-weak/task.md`
- [x] **#023 Sync shipped config defaults and document config options** `C1`
  - `tasks/completed/[2]-023-config-defaults-and-docs/task.md`
- [x] **#029 Extraction quality benchmark** `C2` `superseded by: #032`
  - `tasks/completed/[2]-029-extraction-quality-benchmark/task.md`

### Low

- [x] **#008 Precompute and cache tag embeddings** `C1`
  - `tasks/completed/[3]-008-precompute-tag-embeddings/task.md`

## Ideas

- `tasks/ideas/session-end-reflection.md`
- `tasks/ideas/metaclaw-inspired-adaptation-loop.md` — Explore a retrieval-first adaptation loop: failure-driven engram rewrites, idle-time learning jobs, and benchmark-gated evolution inspired by MetaClaw `→ promoted: #039 (evolution), idle scheduling added to #015`
- `tasks/ideas/precompute-tag-embeddings.md` — Cache tag embeddings used during scoring `→ promoted: #008`
- `tasks/ideas/similarity-floor-threshold.md` — Add minimum vector/BM25 score floors before RRF to prevent noise injection for vague queries `→ partially implemented via min_vector_sim, see #017`
- `tasks/ideas/rrf-tuning-and-alternatives.md` — Explore score-aware fusion or weighted combination instead of rank-only RRF `→ autoresearch testing plan added`
- `tasks/ideas/tool-use-previous-turn-retrieval.md` — Give extraction LLM an on-demand tool to retrieve the previous turn for detecting inflection points
- `tasks/ideas/tag-vocab-normalization.md` — Merge near-duplicate tags in vocab; also prevent bloat at extraction time `→ write-time constraint added`
- `tasks/ideas/enrichment-ground-truth-data.md` — Add `prior_assistant` fields to search_queries.json to enable enrichment strategy testing
- `tasks/ideas/metaclaw-inspired-skill-lifecycle.md` — Session-end synthesis, procedural extraction, versioned evidence, and idle-window maintenance inspired by MetaClaw `→ promoted: #040 (versioning), provenance added to #031, per-turn scoring added to #030`
