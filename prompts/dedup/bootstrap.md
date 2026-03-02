---
name: dedup-bootstrap
description: >
  Mode snippet for bootstrap deduplication — no stable verified pool yet,
  all engrams are candidates for grouping.
goal: >
  Form duplicate groups globally when there is no verified baseline.
model: haiku
variables: []
output_format: Appended to system prompt
used_by:
  - dedup.call_dedup_llm (when mode="bootstrap")
---
You are in BOOTSTRAP mode.

Input may contain only unverified engrams (or mostly unverified).
There is no stable verified pool yet.

Decision rules:
1) Use candidate_edges to reason globally and form duplicate groups.
2) Every input ID must appear exactly once: either in one group or in no_match_ids.
3) Groups may be formed from any IDs in the batch (no verified/unverified restriction).