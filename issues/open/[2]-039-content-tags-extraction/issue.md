# #39 Extract content-specific tags during extraction, merge/prune during dedup

**Severity:** High
**Complexity:** C2

## Problem

All engrams from the same repo get identical environment-detected tags (e.g. `docker, frontend, github, jest, monorepo, react, repo:staff-portal, testing, typescript`). These tags reflect what's in the repo, not what the engram is about. This means tag scoring cannot differentiate between a forms engram and a routing engram — they all score identically within the same repo.

Evidence from session `b5ea4009`: EG#167 (priority profile cascading form deps — relevant) and EG#104 (mainSkillName display — noise) have identical tags and identical tag affinity scores, making it impossible to filter noise by score alone.

## Impact

- Within-repo noise cannot be filtered by tag scoring
- All engrams from the same repo compete equally regardless of topic relevance
- The tag component (40% of score) adds zero differentiation within a repo

## Proposed Solution

### 1. Extract content-specific tags during extraction

When the extraction pipeline creates an engram, also infer topic tags from the content. Examples:
- "The priority profile creation form has cascading field dependencies" → `forms`, `priority-profiles`, `cascading-fields`
- "Import date-fns from @staff-portal/date-time-utils" → `imports`, `date-fns`
- "Jira API tokens can be invalidated server-side" → `jira`, `authentication`

These content tags get stored alongside the environment tags in prerequisites.

### 2. Merge tags during deduplication

When dedup merges two engrams, union the content tags from both. If an engram about "forms" and an engram about "form validation" merge, the result gets both tag sets.

### 3. Prune tags with negative relevance

During evaluation, if a tag has accumulated strong negative relevance scores (from `engrammar_feedback`), remove it from the engram's prerequisites. This naturally cleans up misattributed tags over time.

### 4. Use content tags in search

The search query would match not just the engram text but also its content tags. A query about "modal form" would boost engrams tagged `forms`, `modal` even if those exact words don't appear in the text.

## Notes

- Environment tags (repo, os, mcp_servers) remain as hard/soft gates
- Content tags add within-repo differentiation that environment tags can't provide
- The extraction prompt already runs through an LLM — adding "also suggest 3-5 topic tags" is low overhead
- EG#41 already notes that `_infer_prerequisites` should capture more tags during extraction
