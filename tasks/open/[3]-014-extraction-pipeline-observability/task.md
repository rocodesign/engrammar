# Task: Add Extraction Pipeline Observability

- Priority: Low
- Complexity: C1
- Status: Open

## Problem

The extraction pipeline now coalesces queued turn requests and runs reliably in the background, but it is still hard to distinguish:

- "no useful learnings were present"
- "extraction skipped due to thresholds"
- "pipeline is falling behind"
- "LLM extraction is failing/parsing poorly"

Daemon logs include queue/drain events, but there is no structured view of extraction lag, skip reasons, or failure rates for tuning.

## Goal

Add lightweight observability for the extraction pipeline without introducing heavy metrics infrastructure.

## Fix

1. **Track queue pressure**
   - Log or persist counts for queued turn requests and drain events
   - Include pending queue size in drain logs (already partially present)

2. **Track extraction outcomes**
   - Count `extract_from_turn()` `skipped_reason` values:
     - `no_transcript`
     - `small_transcript`
     - `too_short`
   - Count successful extractions (`added`, `merged`) vs no-op extractions

3. **Track extraction latency**
   - Measure total `process-turn` extraction duration
   - Optionally split into transcript read / LLM call / DB processing phases if easy

4. **Track failure modes**
   - LLM timeout
   - LLM non-zero exit
   - JSON parse failure

5. **Expose an easy inspection path**
   - Start with daemon/extractor logs (structured log lines are enough)
   - Optional follow-up: `engrammar status` / `engrammar log` summary view

## Non-goals

- Full metrics backend / dashboards
- Changing extraction behavior or thresholds
- Alerting/notifications

## Suggested implementation order

1. Add structured log lines for extraction result + duration
2. Add explicit logging for skip reasons and parse/timeout failures
3. Add a small CLI summary (optional)

## Files

- `src/extractor.py` — emit extraction outcome/duration logs
- `src/daemon.py` — queue/drain logging and optional counters
- `cli.py` — optional summary command integration (if added)

