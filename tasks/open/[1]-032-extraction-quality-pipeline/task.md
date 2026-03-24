# Task: Extraction Quality Pipeline — Consolidation, Generalization, Clarity

- Priority: High
- Complexity: C3
- Status: Open

## Problem

The extraction pipeline produces too many engrams that are technically correct but low-value, repetitive, or poorly worded. From a benchmark of 27 transcripts:
- v5 extraction at 8K produced 351 engrams
- Opus quality gate kept 241 (31% rejected)
- LLM dedup merged 18 more → 223 final
- Human review found ~50% are marginal or bad

Three specific quality gaps:

### 1. Consolidation
Multiple engrams about the same library/topic get extracted separately instead of being merged into fewer, richer engrams. Example: 5+ picasso-forms gotchas that could be 1-2 comprehensive ones. Both the extractor and deduplicator need to consolidate related findings.

### 2. Generalization
Engrams are too specific to the exact context where they were discovered. Instead of "Picasso Form.TagSelector overrides value prop", the engram should lead with the general pattern ("form wrapper libraries may override the value prop with form state") then give the specific example. Generic terms help future queries match — a search for "form value override" should find this.

### 3. Clarity to outsiders
Engrams must be understandable to someone who wasn't in the original session. "Do not rename output field names in LLM extraction prompts" is jargon — it should say "When an LLM returns structured JSON, the field names in the prompt's output schema are a contract with your parsing code — don't rename them during refactors."

## Proposed approach

### Extraction prompt (v6)
- Add instruction: "If multiple findings relate to the same library/component, combine them into one engram covering the key gotchas"
- Add instruction: "Lead with the general pattern, then give the specific example. Use generic terms a future query would match."
- Add instruction: "Write engrams that are self-contained — a reader with no session context should understand the problem and the fix"
- Add bad examples showing poor clarity and over-specificity

### Quality gate (post-extraction)
- Two-pass approach validated: v5 extraction (high recall) → opus quality gate (91% accuracy)
- Add "clarity" as an evaluation dimension: "Would someone outside this session understand this?"
- Consider per-transcript budget: "Pick the top N most valuable from this session" to force consolidation

### Dedup prompt
- Instruct deduplicator to consolidate related engrams about the same library/topic into richer combined engrams
- When consolidating, generalize the wording while preserving specific actionable details

## Benchmark infrastructure (partially done)

Built during this session:
- `benchmark/transcripts/evaluation/labeled_engrams.jsonl` — 271 human-labeled engrams with 0-5 value scores
- `benchmark/eval_extraction_quality.py` — eval script with fastembed matching + LLM judge
- `benchmark/prompts/extraction/v1-v5` — extraction prompt variants
- `benchmark/prompts/quality-gate/v1-v3` — quality gate prompt variants
- Source transcripts in `benchmark/transcripts/evaluation/`

Still needed:
- Automated pipeline: extract → quality gate → dedup → score against labeled set
- Per-engram clarity scoring in the quality gate
- Tag accuracy measurement: do extracted content_tags match expected tags (from #029)

## Key findings from benchmarking

| Prompt | Context | Good Recall | Bad Avoidance |
|--------|---------|-------------|---------------|
| production | 8K | 88% | 50% |
| v3-strict | 8K | 75% | 100% |
| v5-balanced | 8K | 85% | 73% |

- 8K context beats 30K on recall (more extraction passes per transcript)
- Opus v1 (simple prompt) is the best quality gate judge: 91% accuracy, 96% good recall, 85% bad rejection
- Structured rejection tests and devil's advocate framing make opus worse, not better
- Haiku is too strict as a judge; avoid it for quality evaluation

## Relation to other tasks

- Supersedes **#029** (extraction quality benchmark) — infrastructure is built
- Complements **#028** (semantic cluster dedup) — consolidation is the quality layer on top of dedup
- Feeds **#012** (stage auto-extracted) — quality pipeline gates what enters the DB

## Files

- `prompts/extraction/transcript.md` — production extraction prompt (update to v6)
- `prompts/dedup/system.md` — dedup system prompt (add consolidation instructions)
- `benchmark/prompts/quality-gate/v1-basic.md` — quality gate prompt (add clarity dimension)
- `benchmark/transcripts/evaluation/labeled_engrams.jsonl` — labeled benchmark data
