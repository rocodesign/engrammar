# Task: Batch Processing for Extracted Engrams

- Priority: Low
- Complexity: C2
- Status: Open

## Problem

`_process_extracted_engrams()` processes extracted items one-by-one and repeats work per engram:

- per-item prerequisite enrichment
- per-item dedup lookup
- per-item DB writes/commits in helper paths
- per-item tag relevance updates

This is fine at current scale, but can become a bottleneck as turn extraction volume grows or if the extractor returns larger batches.

## Goal

Reduce per-turn extraction overhead by batching repeated work without changing extraction semantics.

## Fix

1. **Precompute session-derived context once**
   - Compute reusable session tag data once per turn/session and pass it into prerequisite enrichment
   - Avoid repeated `get_env_tags_for_sessions()` calls for each extracted engram

2. **Single DB transaction per extraction batch**
   - Process the extracted engrams inside one transaction where practical
   - Avoid extra open/commit/close cycles in hot paths

3. **Batch dedup candidate lookup (best-effort)**
   - Embed extracted engrams in a batch and retrieve top-k existing candidates once
   - Keep current merge semantics; this is a performance optimization, not a dedup-policy change

4. **Batch tag relevance updates**
   - Reuse precomputed tag score dicts and minimize repeated DB setup

5. **Preserve one-shot index refresh behavior**
   - Until `#005` is implemented, continue rebuilding once per extraction batch (not per engram)
   - After `#005`, switch batch processing to incremental index updates where beneficial

## Non-goals

- Changing dedup thresholds/heuristics (covered by `#003`)
- Refining merged text with LLMs (covered by `#004`)
- Incremental embedding index mechanics (covered by `#005`)

## Suggested implementation order

1. Precompute session tags once + thread through `_process_extracted_engrams`
2. Consolidate DB writes into fewer transactions
3. Add timing logs around batch processing steps
4. Explore batch dedup candidate retrieval

## Files

- `src/extractor.py` — `_process_extracted_engrams()`, prerequisite enrichment call sites
- `src/db.py` — optional batch-friendly helpers / transaction-aware helpers
- `src/embeddings.py` — optional batch lookup helper for dedup candidate retrieval

