# Task: Stage Auto-Extracted Engrams Before Injection

- Priority: Medium
- Complexity: C3
- Status: Open

## Problem

New `auto-extracted` engrams are immediately treated like mature knowledge. They can be surfaced by hook injection before they have enough evidence, which increases the chance of:

- noisy or weakly phrased advice being injected
- over-scoped engrams being shown in the wrong repos/stacks
- transient one-off learnings polluting hook context

The extractor is intentionally permissive enough to learn quickly. Injection should be stricter than extraction.

## Goal

Introduce a **candidate/staging phase** for newly auto-extracted engrams so extraction remains fast, but hook injection only uses engrams with enough evidence.

## Proposed design

### 1. Add an engram maturity/visibility state

Add a persisted field on `engrams` (name TBD, e.g. `status` or `visibility`) with values like:

- `active` — eligible for normal hook injection/search behavior
- `candidate` — newly auto-extracted; not yet trusted for default hook injection

Defaults:
- Existing engrams (migration/backfill): `active`
- Manual engrams: `active`
- Auto-extracted engrams: `candidate`

## 2. Promotion signals (candidate -> active)

Promote candidates when enough evidence accumulates. Start simple and deterministic:

1. **Recurrence / dedup signal**
   - Candidate merges another occurrence (or `occurrence_count >= 2`)
2. **Positive evaluator signal**
   - Reaches a minimum evidence threshold in `engram_tag_relevance` (exact threshold to tune)
3. **Manual confirmation**
   - User manually updates/pins/categorizes the engram

Promotion should be idempotent and logged.

## 3. Injection behavior changes

Hook injection should exclude candidates by default:

- `UserPromptSubmit` and `PreToolUse` hook searches should only surface `active` engrams
- Pinned engrams should remain `active` (or auto-promote on pin)

Optional future mode:
- Allow candidates behind a stricter score threshold / max-1 slot (not required for first version)

## 4. Search & CLI behavior

Keep candidates visible for inspection/review:

- CLI `list` should show status
- CLI `search` can include candidates by default (or expose `--exclude-candidates` / `--include-candidates`)
- MCP/manual search behavior should be decided explicitly (defaulting to current behavior may be least surprising)

The key point is: **candidate filtering is primarily an injection policy**, not a data-loss mechanism.

## 5. Dedupe and evaluation interactions

Candidates must still fully participate in:

- dedup/merge detection
- occurrence counting
- evaluator scoring updates
- prerequisite/tag generalization work

Otherwise they may never accumulate enough evidence to promote.

## 6. Migration / backward compatibility

- Add schema migration for existing DBs
- Mark all existing rows `active`
- Ensure code paths that read engrams tolerate missing field during migration rollout

## Open questions

- Exact promotion thresholds (recurrence vs evaluator evidence)
- Whether `engrammar_search` (MCP tool) should include candidates by default
- Whether candidate rows should affect ranking statistics the same as active rows
- Whether demotion (`active -> candidate`) is needed (probably not initially)

## Suggested implementation order

1. Schema + migration + DB helpers (`is_candidate`, promote)
2. Mark auto-extracted engrams as `candidate`
3. Exclude candidates from hook injection paths
4. Add promotion on recurrence/manual actions
5. Add evaluator-driven promotion
6. Add CLI visibility and tests

## Files

- `src/db.py` — schema migration, status helpers, active/candidate queries
- `src/extractor.py` — create candidates for auto-extracted engrams, promote on recurrence
- `src/search.py` — candidate filtering knobs (especially for hook paths)
- `hooks/on_prompt.py` — ensure injected results exclude candidates (if handled here)
- `hooks/on_tool_use.py` — ensure injected results exclude candidates (if handled here)
- `src/evaluator.py` — evaluator-driven promotion trigger
- `cli.py` — list/search visibility for candidate status

