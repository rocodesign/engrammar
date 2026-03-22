# Idea: Enrichment-Aware Ground Truth Data

## Problem

The `--enrich` command in autoresearch tests enrichment strategies (strip, strip+file, strip+prior, full), but several ground truth queries are intentionally vague *in isolation* and labeled `relevant`. These queries only make sense with prior conversation context — without `prior_assistant` data, the enrichment strategies have nothing to inject.

Examples from ground truth:
- Q32: "actually let's do it, delete the file before finishing" — `relevant`, expects #401
- Q52: "I mean disable it" — `abstain`, but could be `relevant` with prior context
- Q75: "let's push the branch and create a new PR as is" — `relevant`, expects #162/#163

## What to do

Enrich `search_queries.json` entries with `turn_data.prior_assistant` fields for queries that are conversational continuations. This data would come from the original session transcripts — find the assistant message preceding each query.

Then re-run `--enrich` to measure whether `strip+prior` improves P@1 for vague-but-relevant queries without hurting abstention for true filler.

## Why an idea, not a task

This is data enrichment work, not code. The infrastructure (`--enrich`, `_build_enriched_query`, `strip+prior` strategy) already exists. The bottleneck is manually finding and adding prior context for ~20 queries. Worth doing before investing in more complex enrichment code.
