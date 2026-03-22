# Idea: Tag Vocab Normalization

Priority: Low — embedding similarity already handles near-duplicates (0.82-0.96 cosine), so search quality impact is minimal.

## Problem

The 260-tag vocab has near-duplicates from different LLM calls and backfill runs:
- `dedup` (8) / `deduplication` (6) — sim 0.82
- `migration` (2) / `migrations` (8) — sim 0.94
- `modal` (2) / `modals` (3) — sim 0.92
- `commit` (0) / `commits` (3) — sim 0.87
- `workflow` (9) / `workflows` (1) — sim 0.96

Tag affinity uses embedding similarity so these still match, but the vocab is unnecessarily bloated.

## Potential Fix

1. **Write-time normalization** — when storing a tag, check if a canonical form exists (synonym map or singularization). Merge into canonical before inserting.

2. **One-time cleanup** — merge existing duplicates: pick canonical form per group, update `engram_tags`, rebuild vocab index.

3. **Synonym map** preferred over stemming — stemming would merge `testing`/`test` which may be distinct intents.

## Why Low Priority

The embedding-based tag affinity handles this transparently. `dedup` ↔ `deduplication` scores 0.82 — above the `tag_sim_floor` of 0.50. The only cost is a ~30% larger vocab index (260 vs ~200 canonical), which adds negligible latency.

Revisit if vocab grows past 500+ tags or if exact-match tag operations are added.

## Update (2026-03-22): Prevention at extraction time

A complementary approach to post-hoc cleanup: constrain the extraction LLM to reuse existing tags. The `existing_tags_hint` variable is already passed to the extraction prompt but may not be constraining enough. Strengthening the prompt to say "reuse these tags when applicable, only create new tags for genuinely new topics" would prevent vocab bloat at the source.

This is lower effort than a migration script and addresses the root cause (LLM variance across calls). The one-time cleanup (option 2) is still needed for existing duplicates but becomes a one-shot fix rather than ongoing maintenance.
