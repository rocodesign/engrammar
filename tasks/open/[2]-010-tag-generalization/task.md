# Task: Promote Engrams to Generic When Useful Across Repos

- Priority: Medium
- Complexity: C2
- Status: Open

## Problem

When engrams are extracted, `_enrich_with_session_tags` copies ALL environment tags from the source session into prerequisites. This over-scopes engrams — a universal git rule like "no Co-Authored-By" gets tagged with `["cypress", "frontend", "jest", "monorepo", "react", "repo:testing-platform-frontend-talent", "typescript"]` just because it was extracted from that environment.

The evaluation pipeline then penalizes the engram in other repos because the tag affinity boost treats it as project-specific. Even when the user explicitly applies the rule in another repo, the evaluator may miss it (judging thematic relevance rather than actual application).

## Fix

### 1. Post-evaluation tag generalization

After each evaluation round, check for engrams that are positively scored across multiple distinct `repo:*` tags:

- If `positive_evals > 0` for 2+ different `repo:*` tags in `engram_tag_relevance` → the engram is cross-repo
- Strip all `repo:*` tags from prerequisites, keep only generic tags (`github`, `python`, `testing`, etc.)
- If the remaining generic tags also have mixed signals → remove prerequisites entirely (engram is universal)

### 2. Smarter extraction tagging

In `_enrich_with_session_tags`, use the extraction prompt's `scope` field:
- If scope is `"general"` → don't add repo-specific tags, only add generic ones (language, framework)
- If scope is `"project-specific"` → add all session tags as today

### 3. Evaluator awareness of cross-cutting concerns

The evaluator prompt should recognize that engrams about git, PRs, workflow, and tooling apply regardless of tech stack. "Was this advice acted on?" is the right question, not "does it match the session topic?"

(Partially addressed — evaluator prompt already updated to focus on "was it applied")

## Files

- `src/evaluator.py` — post-evaluation generalization step
- `src/extractor.py` — `_enrich_with_session_tags()` scope-aware tagging
- `src/db.py` — helper to query cross-repo positive evals
