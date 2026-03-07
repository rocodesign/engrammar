# Task: LLM-selected relevant tags during extraction

- Priority: High
- Complexity: C2
- Status: Open

## Problem

When an engram is extracted or re-extracted, `_process_extracted_engrams` scores ALL environment tags with `+0.5` via `update_tag_relevance`. This conflates "observed in this environment" with "relevant to this environment."

Example: EG#1 "The jira skill exists..." was extracted in a TypeScript/React monorepo. It got `+0.5` on `typescript`, `react`, `monorepo`, `jest`, `docker`, etc. — none of which relate to the Jira skill. After 28 re-extractions, `repo:staff-portal` reached 0.999 relevance score, making this engram rank #1 for completely unrelated queries in that repo.

The prerequisite tags (`_enrich_with_session_tags`) have the same problem — they dump the full env tag set into `prerequisites.tags`, which feeds the tag affinity embedding. Generic advice like "search for all references when removing a feature" gets tagged `repo:talent-portal-frontend` + 8 other tags.

## Fix

### 1. Add `relevant_tags` to extraction output

Extend the `transcript.md` extraction prompt to include a `relevant_tags` field. The LLM already sees the engram content and can reason about which env tags actually relate to it.

Pass env tags into the prompt so the LLM can pick from them:

```
Environment tags for this session: ["typescript", "react", "jest", "monorepo", "repo:staff-portal", ...]
```

Output schema becomes:
```json
{
  "engram": "...",
  "category": "...",
  "relevant_tags": ["jest", "testing"],
  "scope": "general" | "project-specific",
  ...
}
```

### 2. Score only relevant tags in `_process_extracted_engrams`

Change from:
```python
tag_scores = {tag: 0.5 for tag in env_tags}
```
To:
```python
relevant = engram_data.get("relevant_tags", [])
tag_scores = {tag: 0.5 for tag in relevant if tag in env_tags}
```

### 3. Use relevant_tags for prerequisites too

Replace `_enrich_with_session_tags` (which dumps all env tags) with the LLM-selected tags:
```python
if relevant:
    prerequisites["tags"] = sorted(set(relevant))
```

### 4. Backfill existing engrams (optional follow-up)

Run a one-time pass over existing engrams to re-derive prerequisites from content, not from historical env tags. Could use the same LLM prompt with the engram text + current tag vocabulary.

## Files

- `prompts/extraction/transcript.md` — add env tags input and `relevant_tags` output field
- `src/pipeline/extractor.py` — pass env_tags to prompt, use `relevant_tags` for scoring and prerequisites
- `src/pipeline/extractor.py:_enrich_with_session_tags` — potentially remove or reduce scope

## Validation

- Extract a few engrams and verify `relevant_tags` are sensible (e.g., "use rspec shared_context" -> `["rspec", "testing", "ruby"]`, not the full env)
- Re-run eval script for both engrammar and staff-portal — verify EG#1-like outliers no longer dominate unrelated queries
- Check that generic engrams get empty or minimal tag sets
