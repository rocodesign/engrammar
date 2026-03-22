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

## MetaClaw-inspired: Idle-aware scheduling for heavy jobs

MetaClaw's `SlowUpdateScheduler` defers expensive operations to idle periods via three signals:

1. **Configurable sleep hours** — e.g., 00:00–07:00 local time
2. **Keyboard inactivity threshold** — no input for N minutes
3. **Calendar integration** — detect meetings via Google Calendar API

For engrammar, heavy jobs that should be deferred to idle windows:

- Full dedup scans (`#003`, `#028`)
- Embedding index rebuilds (`#005`)
- Failure-driven engram evolution (`#039`)
- Extraction benchmark runs (`#029`)
- Session-end synthesis for cross-turn learnings

### Proposed extension to priority queue

Add a third priority tier:

```
Priority 1 (hot):   extraction — always drains first
Priority 2 (warm):  evaluate, dedup — runs when extraction queue empty
Priority 3 (cold):  evolution, full rebuild, benchmarks — only during idle windows
```

### Idle detection for engrammar

Start simple — keyboard inactivity is overkill for a CLI tool:

- **Time-of-day windows** — configurable in `config.json` (e.g., `"idle_hours": [0, 7]`)
- **Session gap detection** — if no new session starts for N minutes, promote cold jobs
- **Explicit trigger** — `engrammar maintenance` CLI command to run cold jobs on demand

Calendar integration is likely not worth the complexity for a dev tool.

## Depends on

- #003 must be working and tested first — the daemon just schedules it, doesn't implement dedup logic itself
