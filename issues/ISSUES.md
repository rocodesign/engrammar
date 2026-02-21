# Engrammar Issues

This file is the index. Detailed issue writeups live under `issues/`.

## How Issues Are Organized

- Open issues live in `issues/open/`, one folder per issue.
- Resolved issues live in `issues/resolved/`.
- Open issue folder names use a severity priority prefix:
  - `[1]-...` = Critical
  - `[2]-...` = High
  - `[3]-...` = Medium
  - `[4]-...` = Low
- Each issue has `issue.md` with problem, impact, and high-level solution.

## Complexity Scale

- `C1` = low complexity (low-hanging)
- `C2` = medium complexity
- `C3` = high complexity

## Open Issues by Severity

### Critical
- None currently identified.

### High
- [ ] **#19 Errors remain fail-open and mostly silent to users** `[C2]`
  - `issues/open/[2]-019-errors-silent-fail-open/issue.md`
- [ ] **#23 Path prerequisite matching false-matches on prefixes** `[C1] low-hanging`
  - `issues/open/[2]-023-path-prereq-prefix-match/issue.md`
- [ ] **#26 Pin/unpin evidence can be overcounted when many tags are scored at once** `[C3]`
  - `issues/open/[2]-026-pin-evidence-overcount/issue.md`
- [ ] **#28 Pending evaluation processing has no claim/lock step** `[C3]`
  - `issues/open/[2]-028-evaluator-no-claim-lock/issue.md`
- [ ] **#29 Shown-engram backfill uses present-day engram set** `[C2]`
  - `issues/open/[2]-029-backfill-shown-engrams-temporal-leakage/issue.md`
- [ ] **#30 JSON array parser can return wrong array shape** `[C1] low-hanging`
  - `issues/open/[2]-030-json-array-parser-first-bracket/issue.md`
### Medium
- [ ] **#7 Daemon is single-threaded** `[C3]`
  - `issues/open/[3]-007-single-threaded-daemon/issue.md`
- [ ] **#8 Config cached per-process but daemon is long-lived** `[C1] low-hanging`
  - `issues/open/[3]-008-config-cache-daemon/issue.md`
- [ ] **#12 Full index rebuild on every engram add** `[C3]`
  - `issues/open/[3]-012-full-index-rebuild-on-add/issue.md`
- [ ] **#13 Backfill repo detection is path-layout dependent** `[C1] low-hanging`
  - `issues/open/[3]-013-backfill-repo-detection-layout-dependent/issue.md`
- [ ] **#15 Connection management in `update_match_stats` is fragile** `[C2]`
  - `issues/open/[3]-015-update-match-stats-connection-fragility/issue.md`
- [ ] **#22 CLI `update --category` doesn't sync `level1/level2/level3`** `[C1] low-hanging`
  - `issues/open/[3]-022-cli-update-category-level-drift/issue.md`
- [ ] **#27 Tag relevance boost averages only known-tag rows** `[C1] low-hanging`
  - `issues/open/[3]-027-tag-relevance-average-sparse/issue.md`
- [ ] **#31 Session-end tests can spawn real CLI jobs** `[C1] low-hanging`
  - `issues/open/[3]-031-session-end-tests-spawn-real-cli/issue.md`

### Low
- [ ] **#5 `sys.path.insert(0, ENGRAMMAR_HOME)` everywhere** `[C3]`
  - `issues/open/[4]-005-sys-path-insert/issue.md`
- [ ] **#9 CLI argument parsing is hand-rolled** `[C2]`
  - `issues/open/[4]-009-cli-argparse/issue.md`
- [ ] **#14 `datetime.utcnow()` is deprecated** `[C1] low-hanging`
  - `issues/open/[4]-014-datetime-utcnow-deprecated/issue.md`

## Resolved / Closed

- [x] **#1-#4 Tag-relevance redesign and migration work**
  - `issues/resolved/001-004-tag-relevance-redesign/issue.md`
- [x] **#6 Race condition on `.session-shown.json`**
- [x] **#10 Duplicate utility code across hooks**
- [x] **#11 `find_similar_engram` vector fallback added**
- [x] **#16 MCP input validation minimal (outdated claim)**
- [x] **#17 Coverage gaps in CLI/MCP/hooks (outdated claim)**
- [x] **#18 `register_hooks.py` dead code (outdated claim)**
- [x] **#20 `test_tag_stats.py` corrupted**
- [x] **#21 Backfill used current environment for historical sessions**
- [x] **#24 Session identity global/local UUID mapping issue**
- [x] **#25 Evaluator transcript lookup weakly coupled to session IDs**
