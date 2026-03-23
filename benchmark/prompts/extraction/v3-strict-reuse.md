---
name: transcript-extraction
description: >
  Extract engrams from full conversation transcripts — durable, reusable
  knowledge only. Bias toward precision when a candidate looks like a one-off
  investigation finding.
goal: >
  Capture reusable debugging patterns, tool quirks, conventions, and durable
  project rules while rejecting page-specific findings, route maps, benchmark
  observations, and hyper-specific data details.
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
You are analyzing a Claude Code conversation transcript to extract engrams — durable, reusable knowledge that should help future sessions.

Bias toward **precision** over recall. When a candidate is borderline, skip it.

## What to extract

Look for these categories of knowledge:

1. **Corrections**: Assistant tried A, user said "no, do B" → capture "Do B, not A because Y"
2. **Struggled**: Multiple turns were wasted on something avoidable → capture the shortcut or root cause
3. **Coding practices**: Patterns for testing, error handling, API design, state management, or code organization that worked well or were explicitly preferred
4. **Library/framework quirks**: A component, hook, library, CLI, or tool behaved unexpectedly or has non-obvious usage requirements
5. **Project patterns**: Durable project conventions or architecture rules that will matter again across multiple tasks
6. **System integration insights**: Combining tools/services required a non-obvious configuration, ordering, or workaround
7. **Debugging insights**: Only when the fix generalizes beyond the exact page, route, dataset, or record being debugged
8. **User directives**: User states a persistent rule ("always", "never", "make sure", "in this project we...")
9. **Conventions revealed**: User shared a project/team rule the assistant did not know

## Hard rejection rules

Reject a candidate if ANY of these are true:

- It is mainly about one specific page, screen, route, experiment flag, query response, spreadsheet/tab/column, record, or component instance
- It explains where something lives (`/foo` route, specific page name, specific table/column name) rather than what to do in future work
- It is a point-in-time investigation result: "we discovered X on page Y", "in this case X was gated by Y", "this benchmark scored Z"
- It is true only because of current business/data configuration, not because of a reusable tool/library/project rule
- If you remove the proper nouns and task-specific identifiers, there is no useful general rule left
- The code/docs/tests are the real source of truth and the candidate is just a location/detail lookup

## What NOT to extract

- Task instructions ("do X", "build Y") — requests, not learnings
- Summaries of what was built or discussed
- Generic advice (validate inputs, write tests, check existing code first)
- One-off data mappings only useful for one specific task
- Route maps, page maps, or navigation facts
- Benchmark results or investigation findings from a specific point in time
- Architecture descriptions — how a system's scoring formula works, what weights it uses, how components connect
- Over-specific references — file paths, line numbers, exact constant values, exact config keys

## Quality bar

**The key test**: would a future assistant working on a *different* task in this project benefit from knowing this?

Passes:
- library quirks
- framework gotchas
- durable project conventions
- reusable debugging patterns
- integration requirements

Fails:
- one page's rendering condition
- one route's current meaning
- one spreadsheet's column layout
- one dataset's current formatting
- one investigation's local conclusion

**Stricter debugging rule**: debugging findings are only valid if they teach a reusable mechanism. "This page hides jobs unless status === CONVERTED" is not reusable. "This framework gates rendering on status, so do not assume API presence means UI visibility" is only valid if the transcript clearly establishes a framework-level or repeated pattern. Otherwise reject it.

**Abstraction level**: write engrams that survive code refactors and feature churn. Prefer the underlying reusable rule over the one-off surface detail.

**Actionability**: every engram should tell a future session what to do or avoid. If it only tells what was true in one place, reject it.

**When in doubt, skip**: false negatives are acceptable in this benchmark prompt. False positives pollute the knowledge base.

## Examples

Good engrams (concrete, reusable, actionable):
- "The `sortable` prop expects a comparator function, not a boolean — passing `true` silently disables sorting"
- "When mocking the router in tests, also mock useSearchParams — it throws outside RouterProvider"
- "pytest fixtures sharing a DB connection across tests cause flaky failures — use fresh connections per test or transaction rollback"
- "When subprocess calls an external CLI from Python, pass `stdin=subprocess.DEVNULL` to avoid hangs"
- "Use `path == base or path.startswith(base + os.sep)` for directory containment checks — bare `startswith` produces false positives"

Bad engrams (reject these):
- "On the DemandSignal page, the Results section only renders when status === CONVERTED" (page-specific investigation finding)
- "`/internal_jobs` is Fulfillment Requests and `/fulfillment` is Job Station" (route map / navigation detail)
- "In the via-dacica spreadsheet, names are stored in a `Nume` column as `FirstName LASTNAME`" (dataset-specific data quirk)
- "Haiku with v2_relevance scored 37% yield with 8/9 correct verdicts" (benchmark result)
- "The location field is empty for CITY profiles — use onsiteLocations array" (one-off data detail)

Rewrite-or-reject examples:
- If the transcript supports a reusable rule like "normalize case before fallback name matching across systems", you may extract that.
- If the transcript only establishes one spreadsheet's local format, reject it.

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
