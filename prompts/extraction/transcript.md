---
name: transcript-extraction
description: >
  Extract engrams from full conversation transcripts — reusable knowledge about
  coding practices, library quirks, project patterns, and system integration insights.
goal: >
  Maximize recall of durable, actionable knowledge while filtering out
  task summaries, one-off details, benchmark results, and generic advice.
variables:
  - transcript
  - session_id
  - existing_instructions
  - env_tags
  - existing_tags_hint
output_format: JSON array of {category, engram, source_sessions, project_signals, relevant_tags, content_tags}
used_by:
  - extractor._call_claude_for_transcript_extraction
  - extractor.reextract_engrams (via chunked extraction)
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
7. **Debugging insights**: When the model hit errors while testing or running code, and the fix was non-obvious → capture what went wrong and how to fix it
8. **User directives**: User states a persistent rule ("always", "never", "make sure", "in this project we...") → capture it
9. **Conventions revealed**: User shared a project/team rule the assistant didn't know → capture the rule

## What NOT to extract

- Task instructions ("do X", "build Y") — these are requests, not learnings
- Summaries of what was built or discussed
- Generic advice (validate inputs, write tests, check existing code first)
- One-off data mappings only useful for one specific task ("field X is empty, use field Y")
- Benchmark results or investigation findings from a specific point in time ("model X scored 37% on test Y") — these are log entries, not durable rules
- Architecture descriptions — how a system's scoring formula works, what weights it uses, how components connect. These are documentation, not reusable rules.
- Over-specific references — file paths, line numbers, exact constant values, and config keys change frequently. Capture the *insight*, not the coordinates.

## Quality bar

**The key test**: would a future assistant working on a *different* task in this project benefit from knowing this? Gotchas about libraries, design system components, build tools, testing frameworks, project conventions, and integration patterns all pass this test. One-off investigation results, benchmark numbers, and task-specific data details do not.

**Abstraction level**: Write engrams that survive code refactors. Prefer "low relevance weights have minimal impact on blend scoring" over "RELEVANCE_WEIGHT=0.005 in search.py is too small". The insight should remain true even if files move, constants get renamed, or code gets reorganized.

**Actionability**: Every engram should tell a future session what to *do* or *avoid*. "Use X when Y" is actionable. "X scored 37%" is not.

## Examples

Good engrams (concrete, reusable, actionable):
- "The `sortable` prop expects a comparator function, not a boolean — passing `true` silently disables sorting"
- "When mocking the router in tests, also mock useSearchParams — it throws outside RouterProvider"
- "pytest fixtures sharing a DB connection across tests cause flaky failures — use fresh connections per test or use transaction rollback"
- "The daemon caches Python modules at startup — restart it after deploying code changes or the running instance uses stale code"
- "Schema migrations must be backward-compatible because the old version runs during rolling deploys — add new columns as nullable first"
- "When subprocess.run hangs in CI, it's usually a missing `timeout` param — always set timeout on subprocess calls to external tools"

Bad engrams (task summaries, generic, one-off, over-specific, benchmark results):
- "Rebuild similarity index after each batch" (user instruction, not a correction)
- "Before building a component, check if one exists" (generic process advice)
- "The location field is empty for CITY profiles — use onsiteLocations array" (one-off data detail)
- "RELEVANCE_WEIGHT=0.005 in search.py line 68 is too small" (over-specific — tied to exact file/line/value)
- "The blend scoring formula uses w_semantic * rrf_norm + w_tag * tag_norm with weights 0.60/0.40" (architecture description, not a reusable rule)
- "Haiku with v2_relevance scored 37% yield with 8/9 correct verdicts" (benchmark result — not actionable guidance)

## Deduplication

The project has these instructions already documented — DO NOT extract engrams that restate or duplicate this information:
{existing_instructions}
{existing_tags_hint}

Environment tags detected for this session: {env_tags}

Session transcript:
{transcript}

Output a JSON array of objects, each with:
- "category": hierarchical path — "development/frontend", "development/testing", "tools/<name>", "workflow/<area>", "general/<topic>". Be specific.
- "engram": the concrete rule (1-2 sentences max)
- "source_sessions": ["{session_id}"]
- "project_signals": project/tool names mentioned in the engram (e.g. ["nx", "jest"]), else []
- "relevant_tags": (deprecated, kept for backward compat) subset of the environment tags above that the engram's content actually relates to. Only include tags the engram is *about* — not every tag present in the session. Generic advice should have an empty list []. This field is no longer used for scoring — content_tags below replaces it.
- "content_tags": 1-3 short topic labels describing what the engram is about, independent of the project environment. These should be lowercase, specific, and capture the domain/tool/concept. Examples: ["testing", "react", "rtl"], ["git", "rebasing"], ["forms", "validation"], ["jira", "authentication"]. Generic engrams can have content_tags like ["dev-workflow"] or ["conventions"]. Do NOT use environment tags here — use topic-level labels only. Do NOT include the repository name as a content tag (e.g. "engrammar", "staff-portal") — a repo:X tag is already added automatically.

If no engrams are worth extracting, output an empty array: []

Output ONLY valid JSON, no markdown fences, no explanation.