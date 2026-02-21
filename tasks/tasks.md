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

- [ ] **#007 Extract lessons at session end** `C2`
  - `tasks/open/[1]-007-session-end-extraction/task.md`

### Medium

- [ ] **#003 Strengthen lesson deduplication** `C2`
  - `tasks/open/[2]-003-lesson-dedup-too-weak/task.md`
- [ ] **#004 LLM-assisted lesson refinement on merge** `C2` `blocked-by: #003, #005`
  - `tasks/open/[2]-004-llm-assisted-lesson-merge/task.md`
- [ ] **#005 Incremental embedding index update** `C2`
  - `tasks/open/[2]-005-incremental-embedding-index/task.md`

## Completed Tasks

### High

- [x] **#001 Fix self-extraction fake session IDs** `C1`
  - `tasks/completed/[1]-001-self-extraction-fake-session-ids/task.md`
- [x] **#006 Deduplicate lesson injection globally per session** `C1`
  - `tasks/completed/[1]-006-dedup-lessons-per-session/task.md`

### Medium

- [x] **#002 Fix extraction prompt wrong categories** `C1`
  - `tasks/completed/[2]-002-extraction-wrong-categories/task.md`

## Ideas

- `tasks/ideas/session-end-reflection.md`
