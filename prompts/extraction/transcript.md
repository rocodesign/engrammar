---
name: transcript-extraction
description: >
  Extract engrams from full conversation transcripts by identifying friction
  patterns where the assistant got something wrong and the user corrected it.
goal: >
  Maximize recall of reusable project-specific knowledge while filtering out
  task summaries, one-off details, and generic advice.
model: haiku
variables:
  - transcript
  - session_id
  - existing_instructions
  - env_tags
  - existing_tags_hint
output_format: JSON array of {category, engram, source_sessions, scope, project_signals, relevant_tags, content_tags}
used_by:
  - extractor._call_claude_for_transcript_extraction
  - extractor.reextract_engrams (via chunked extraction)
---
You are analyzing a Claude Code conversation transcript to extract engrams — concrete rules learned from friction.

Extract when the assistant got corrected, struggled, or the user revealed how things actually work:
1. **Corrections**: Assistant tried A, user said "no, do B" → capture "Do B, not A because Y"
2. **Struggled**: Multiple turns wasted on something avoidable → capture the shortcut or root cause
3. **Conventions revealed**: User shared a project/team rule the assistant didn't know → capture the rule
4. **API/library gotchas**: A component, hook, library, or tool behaved unexpectedly → capture the gotcha
5. **User directives**: User states a persistent rule ("always", "never", "make sure", "in this project we...") → capture it

DO NOT extract:
- Task instructions ("do X", "build Y") — these are requests, not learnings
- Summaries of what was built or discussed
- Generic advice (validate inputs, write tests, check existing code first)
- One-off data mappings only useful for one specific task ("field X is empty, use field Y")
- Architecture descriptions — how a system's scoring formula works, what weights it uses, how components connect. These are documentation, not friction-learned rules.
- Over-specific references — file paths, line numbers, exact constant values, and config keys change frequently. Capture the *insight*, not the coordinates.

**The key test**: would a future assistant working on a *different* task in this project benefit from knowing this? Gotchas about libraries, design system components, build tools, testing frameworks, and project conventions all pass this test. One-off field mappings and task-specific data details do not.

**Abstraction level**: Write engrams that survive code refactors. Prefer "low relevance weights have minimal impact on blend scoring" over "RELEVANCE_WEIGHT=0.005 in search.py is too small". The insight should remain true even if files move, constants get renamed, or code gets reorganized.

Good engrams (concrete, reusable):
- "The `sortable` prop expects a comparator function, not a boolean — passing `true` silently disables sorting"
- "When mocking the router in tests, also mock useSearchParams — it throws outside RouterProvider"
- "In this monorepo, run codegen scoped to the app (nx run app:codegen), not workspace-wide"
- "Import order matters — group external imports before internal or CI lint fails"

Bad engrams (task summaries, generic, one-off, over-specific):
- "Rebuild similarity index after each batch" (user instruction, not a correction)
- "Before building a component, check if one exists" (generic process advice)
- "The location field is empty for CITY profiles — use onsiteLocations array" (one-off data detail)
- "RELEVANCE_WEIGHT=0.005 in search.py line 68 is too small" (over-specific — tied to exact file/line/value)
- "The blend scoring formula uses w_semantic * rrf_norm + w_tag * tag_norm with weights 0.60/0.40" (architecture description, not a friction-learned rule)
{existing_instructions}{existing_tags_hint}
Environment tags detected for this session: {env_tags}

Session transcript:
{transcript}

Output a JSON array of objects, each with:
- "category": hierarchical path — "development/frontend", "development/testing", "tools/<name>", "workflow/<area>", "general/<topic>". Be specific.
- "engram": the concrete rule (1-2 sentences max)
- "source_sessions": ["{session_id}"]
- "scope": "general" or "project-specific"
- "project_signals": project/tool names when scope is "project-specific", else []
- "relevant_tags": (deprecated, kept for backward compat) subset of the environment tags above that the engram's content actually relates to. Only include tags the engram is *about* — not every tag present in the session. Generic advice should have an empty list []. This field is no longer used for scoring — content_tags below replaces it.
- "content_tags": 1-3 short topic labels describing what the engram is about, independent of the project environment. These should be lowercase, specific, and capture the domain/tool/concept. Examples: ["testing", "react", "rtl"], ["git", "rebasing"], ["forms", "validation"], ["jira", "authentication"]. Generic engrams can have content_tags like ["dev-workflow"] or ["conventions"]. Do NOT use environment tags here — use topic-level labels only.

If no engrams are worth extracting, output an empty array: []

Output ONLY valid JSON, no markdown fences, no explanation.