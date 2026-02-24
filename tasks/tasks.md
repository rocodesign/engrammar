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

### Medium

- [ ] **#003 Strengthen engram deduplication** `C2`
  - `tasks/open/[2]-003-engram-dedup-too-weak/task.md`
- [ ] **#004 LLM-assisted engram refinement on merge** `C2` `blocked-by: #003, #005`
  - `tasks/open/[2]-004-llm-assisted-engram-merge/task.md`
- [ ] **#005 Incremental embedding index update** `C2`
  - `tasks/open/[2]-005-incremental-embedding-index/task.md`
- [ ] **#009 Richer tool-use context for PreToolUse search** `C2`
  - `tasks/open/[2]-009-richer-tool-use-context/task.md`
- [ ] **#010 Promote engrams to generic when useful across repos** `C2`
  - `tasks/open/[2]-010-tag-generalization/task.md`

## Completed Tasks

### High

- [x] **#001 Fix self-extraction fake session IDs** `C1`
  - `tasks/completed/[1]-001-self-extraction-fake-session-ids/task.md`
- [x] **#006 Deduplicate engram injection globally per session** `C1`
  - `tasks/completed/[1]-006-dedup-engrams-per-session/task.md`
- [x] **#007 Per-turn extraction via Stop hook** `C2`
  - `tasks/completed/[1]-007-session-end-extraction/task.md`

### Medium

- [x] **#002 Fix extraction prompt wrong categories** `C1`
  - `tasks/completed/[2]-002-extraction-wrong-categories/task.md`

### Low

- [x] **#008 Precompute and cache tag embeddings** `C1`
  - `tasks/completed/[3]-008-precompute-tag-embeddings/task.md`

## Ideas

- `tasks/ideas/session-end-reflection.md`
- `tasks/ideas/similarity-floor-threshold.md` — Add minimum vector/BM25 score floors before RRF to prevent noise injection for vague queries
- `tasks/ideas/rrf-tuning-and-alternatives.md` — Explore score-aware fusion or weighted combination instead of rank-only RRF
