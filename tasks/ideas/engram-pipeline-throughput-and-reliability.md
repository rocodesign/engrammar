# Idea: Engram Pipeline Throughput and Reliability Hardening

Improve the real-time engram pipeline under active sessions by separating slow work, handling backlog explicitly, and reducing low-confidence injections from freshly extracted engrams.

## Why this matters

Per-turn extraction is a strong improvement, but the current flow still has a few reliability/performance bottlenecks:

- `src/daemon.py` runs `process-turn` as a single `extract_proc` job and returns `already_running` if another turn arrives.
- `cli.py` `cmd_process_turn()` runs **extraction and evaluation** in the same job, so slow evaluation increases the time the extract slot is occupied.
- `src/extractor.py` `extract_from_turn()` can catch up via byte offsets, but under sustained activity it may stay behind for long periods.
- Newly auto-extracted engrams can be injected immediately, which risks surfacing noisy or over-scoped advice before enough evidence accumulates.

## Ideas

### ~~1. Split extraction and evaluation in the turn path~~ (Done)

`process-turn` is now extraction-only. Daemon schedules evaluation on separate `evaluate_proc` slot concurrently.

### ~~2. Add backlog coalescing instead of drop-on-busy~~ (Done — task #011)

Daemon maintains `_pending_turns` dict, coalesced per session. Drain runs after connections and on 5s timeout polls.

### 3. Track extraction lag and skip reasons

Persist lightweight metrics (or append-only logs) for:
- `already_running` responses
- `skipped_reason` counts (`small_transcript`, `too_short`, `no_transcript`)
- extraction duration
- parse failures / timeouts

Without this, it is hard to tell whether "no new engrams" means "nothing to learn" or "pipeline fell behind."

### 4. Add a confidence/staging phase for auto-extracted engrams

Treat fresh auto-extracted engrams as "candidate" items until they have enough evidence:
- duplicate/merge recurrence (`occurrence_count >= 2`)
- positive evaluator signal
- manual pin/update

Candidate engrams could be:
- searchable for manual review
- excluded from hook injection by default, or injected with a stricter score threshold

This should improve injection reliability without slowing extraction.

### 5. Batch processing in `_process_extracted_engrams`

Current processing loops one-by-one and repeats some work per extracted item (DB lookups, similarity checks, tag updates).
Possible follow-up optimizations:
- precompute session-derived prerequisites/tags once per turn
- batch similarity candidate lookup for extracted items
- commit DB changes in one transaction per turn

This is complementary to incremental embeddings (`#005`), not a replacement.

## Suggested implementation order

1. ~~Split extraction/evaluation in `process-turn`~~ Done
2. ~~Add backlog coalescing~~ Done (task #011) — lag metrics remain as #3
3. Track extraction lag and skip reasons
4. Add candidate/staging status for auto-extracted engrams (task #012)
5. Batch `_process_extracted_engrams` internals (task #013)

