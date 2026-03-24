---
name: transcript-extraction-v5
description: >
  Extract engrams from full conversation transcripts — reusable knowledge about
  coding practices, library quirks, project patterns, and system integration insights.
  v5: combines v3's abstract rejection rules with v4's recall-friendly categories.
goal: >
  Maximize recall of durable, actionable knowledge while filtering out
  task summaries, one-off details, benchmark results, and generic advice.
model: haiku
variables:
  - transcript
  - session_id
  - existing_instructions
  - env_tags
  - existing_tags_hint
output_format: JSON array of {category, engram, source_sessions, project_signals, relevant_tags, content_tags}
used_by:
  - benchmark/run_extraction.py
---
You are analyzing a Claude Code conversation transcript to extract engrams — durable, reusable knowledge that helps future sessions.

## What to extract

Look for these categories of knowledge:

1. **Corrections**: Assistant tried A, user said "no, do B" → capture "Do B, not A because Y"
2. **Struggled**: Multiple turns wasted on something avoidable → capture the shortcut or root cause
3. **Coding practices**: Patterns for error handling, testing strategies, API design, or code organization that worked well or were explicitly preferred → capture the practice
4. **Library/framework quirks**: A component, hook, library, or tool behaved unexpectedly or has non-obvious usage patterns → capture the gotcha
5. **Project patterns**: How services connect, what the deployment pipeline expects, naming conventions, file organization rules → capture the pattern
6. **System integration insights**: When combining tools/services, something required a non-obvious configuration, ordering, or workaround → capture the integration requirement
7. **Debugging insights**: Only when the fix generalizes beyond the exact page, route, dataset, or record being debugged
8. **User directives**: User states a persistent rule ("always", "never", "make sure", "in this project we...") → capture it
9. **Conventions revealed**: User shared a project/team rule the assistant didn't know → capture the rule

## Rejection test

Before including a candidate, apply these checks. Reject if ANY is true:

1. **Proper-noun test**: remove the specific page names, route paths, column names, component instances, and dataset identifiers. Is there still a useful general rule? If not, reject.
2. **Frequency test**: would this come up repeatedly across different tasks in this project, or does it only matter for one narrow workflow? If it's a one-time finding, reject.
3. **Durability test**: would this become false after the current task completes — a feature flag removed, a threshold retuned, a refactor landed? If yes, reject.
4. **Source-of-truth test**: is the code, commit, or docs already the authoritative record for this? If the engram is just restating what the code says, reject.

## What NOT to extract

- Task instructions ("do X", "build Y") — requests, not learnings
- Summaries of what was built or discussed
- Generic advice (validate inputs, write tests, check existing code first)
- One-off data mappings, field layouts, or column formats for one specific model/spreadsheet/API
- Route maps, page maps, or navigation facts — where things live belongs in docs
- Benchmark results, scores, or investigation findings from a specific point in time
- Architecture descriptions — how a formula works, what weights it uses, how components connect
- Over-specific references — file paths, line numbers, exact constant values
- Implementation logs — what was just built/refactored in this session is recorded in the commit

## Quality bar

**The key test**: would a future assistant working on a *different* task in this project benefit from knowing this?

Passes: library quirks, framework gotchas, durable project conventions, reusable debugging patterns, integration requirements, user preferences that apply broadly.

Fails: one page's rendering condition, one route's current meaning, one dataset's formatting, one investigation's local conclusion, one benchmark's numbers, one refactoring's implementation details.

**Abstraction level**: write engrams that survive code refactors and feature churn. Capture the underlying reusable rule, not the surface detail.

**Actionability**: every engram should tell a future session what to do or avoid. If it only reports what was true in one place, reject it.

## Examples

Good engrams (concrete, reusable, actionable):
- "The `sortable` prop expects a comparator function, not a boolean — passing `true` silently disables sorting"
- "When mocking the router in tests, also mock useSearchParams — it throws outside RouterProvider"
- "pytest fixtures sharing a DB connection across tests cause flaky failures — use fresh connections per test or transaction rollback"
- "When subprocess calls an external CLI from Python, pass `stdin=subprocess.DEVNULL` to avoid hangs"
- "Use `path == base or path.startswith(base + os.sep)` for directory containment checks — bare `startswith` produces false positives"
- "Schema migrations must be backward-compatible during rolling deploys — add new columns as nullable first"

Bad engrams (reject these):
- "Rebuild similarity index after each batch" (task instruction, not a learned rule)
- "Before building a component, check if one exists" (generic process advice)
- "The budget spreadsheet stores names as FirstName LASTNAME in all caps" (one dataset's format — fails proper-noun test)
- "Use config X with model Y for evaluation — it scored 37% yield" (benchmark result with score — fails durability test)
- "We removed the scope field and updated the tests" (implementation log — fails source-of-truth test)
{existing_instructions}{existing_tags_hint}
Environment tags detected for this session: {env_tags}

Session transcript:
{transcript}

Output a JSON array of objects, each with:
- "category": hierarchical path — "development/frontend", "development/testing", "tools/<name>", "workflow/<area>", "general/<topic>". Be specific.
- "engram": the concrete rule (1-2 sentences max)
- "source_sessions": ["{session_id}"]
- "project_signals": project/tool names mentioned in the engram (e.g. ["nx", "jest"]), else []
- "relevant_tags": (deprecated, kept for backward compat) subset of the environment tags above that the engram's content actually relates to. Only include tags the engram is *about* — not every tag present in the session. Generic advice should have an empty list [].
- "content_tags": 1-3 short topic labels describing what the engram is about, independent of the project environment. These should be lowercase, specific, and capture the domain/tool/concept. Do NOT use environment tags here. Do NOT include the repository name as a content tag — a repo:X tag is added automatically.

If no engrams are worth extracting, output an empty array: []

Output ONLY valid JSON, no markdown fences, no explanation.