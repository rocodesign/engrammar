---
name: dedup-incremental
description: >
  Mode snippet for incremental deduplication — unverified engrams checked
  against a stable verified pool.
goal: >
  Decide each unverified engram: merge into verified or mark as unique.
model: haiku
variables: []
output_format: Appended to system prompt
used_by:
  - dedup.call_dedup_llm (when mode="incremental")
---
You are in INCREMENTAL mode.

Input contains:
- UNVERIFIED engrams that must be decided this pass
- VERIFIED candidate engrams that may be merge targets/bridges

Decision rules:
1) For each unverified engram, decide if it duplicates any verified candidate.
2) If a verified candidate bridges multiple unverified engrams, you may form one multi-ID group.
3) Every unverified ID must appear exactly once: either in one group or in no_match_ids.
4) Verified-only IDs must not appear in no_match_ids.
5) Every group must include at least one unverified ID.