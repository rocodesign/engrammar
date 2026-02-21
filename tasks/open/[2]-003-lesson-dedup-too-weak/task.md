# Task: Strengthen Engram Deduplication

- Priority: Medium
- Complexity: C2
- Related issue: `issues/open/[3]-029-engram-dedup-too-weak/issue.md`
- Status: Open

## Problem

Word-overlap (0.70) and embedding similarity (0.85) miss near-duplicates. Multiple clusters of 2-4 engrams say the same thing:
- #2, #12, #27 — branch naming `taps-NUMBER`
- #7, #22, #28 — PR descriptions max 50 words
- #10, #15, #25, #32 — don't auto-post PR comments
- #8, #14 — clarify bug symptoms before fixing

## Fix

1. **Lower embedding threshold** from 0.85 to ~0.75 for merge detection in `find_similar_engram`.
2. **LLM second-pass dedup**: When `find_similar_engram` returns None but top-3 embedding matches are above 0.60, send them to Haiku with a yes/no "is this the same engram?" prompt. Only merge on "yes".
3. **CLI `dedup` command**: Scan all active engrams pairwise (via embeddings), flag clusters above a similarity threshold, optionally merge with `--apply`.

## Files

- `src/db.py` — `find_similar_engram` threshold
- `src/extractor.py` — LLM dedup second-pass
- `cli.py` — `dedup` command
