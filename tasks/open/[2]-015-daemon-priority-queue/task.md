# Task: Daemon Priority Queue with Background Dedup

- Priority: Medium
- Complexity: C2
- Blocked by: #003 (LLM-assisted dedup logic)
- Status: Open

## Problem

The daemon currently runs extraction and evaluation on two independent concurrent proc slots. Adding dedup as a third concern makes the concurrency model harder to reason about. We also want extraction to always take priority — eval and dedup are background work that shouldn't compete with the hot path.

## Design

Replace the two-slot concurrent model (`extract_proc` + `evaluate_proc`) with a single worker slot and priority queue:

```
Turn comes in → queue extraction (high priority)
                ↓
Drain loop:
  1. If pending extractions → run next extraction
  2. If no pending extractions → promote one background job
     - evaluate (unchecked engrams)
     - dedup (unverified engrams)
```

### Priority rules

- **Extraction** (high): always drains first. Same coalescing queue as today.
- **Evaluate / Dedup** (low): only promoted when extraction queue is empty. Worker finishes current job before checking queue — no preemption.

### Single worker slot

One `worker_proc` replaces `extract_proc` + `evaluate_proc`. Simpler to reason about, and background work is naturally serialized.

### Integration with #003

The dedup job calls the same logic built in #003 — pick unverified engrams, run LLM comparison, merge or mark verified. The daemon just schedules it as a background job type.

## Files

- `src/daemon.py` — priority queue, single worker slot, `_next_background_job()`, updated drain logic
- Tests for priority ordering and promotion behavior

## Depends on

- #003 must be working and tested first — the daemon just schedules it, doesn't implement dedup logic itself
