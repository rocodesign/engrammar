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
output_format: JSON array of {category, engram, source_sessions, scope, project_signals}
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

**The key test**: would a future assistant working on a *different* task in this project benefit from knowing this? Gotchas about libraries, design system components, build tools, testing frameworks, and project conventions all pass this test. One-off field mappings and task-specific data details do not.

Good engrams (concrete, reusable):
- "The `sortable` prop expects a comparator function, not a boolean — passing `true` silently disables sorting"
- "When mocking the router in tests, also mock useSearchParams — it throws outside RouterProvider"
- "In this monorepo, run codegen scoped to the app (nx run app:codegen), not workspace-wide"
- "Import order matters — group external imports before internal or CI lint fails"

Bad engrams (task summaries, generic, one-off):
- "Rebuild similarity index after each batch" (user instruction, not a correction)
- "Before building a component, check if one exists" (generic process advice)
- "The location field is empty for CITY profiles — use onsiteLocations array" (one-off data detail)
{existing_instructions}
Session transcript:
{transcript}

Output a JSON array of objects, each with:
- "category": hierarchical path — "development/frontend", "development/testing", "tools/<name>", "workflow/<area>", "general/<topic>". Be specific.
- "engram": the concrete rule (1-2 sentences max)
- "source_sessions": ["{session_id}"]
- "scope": "general" or "project-specific"
- "project_signals": project/tool names when scope is "project-specific", else []

If no engrams are worth extracting, output an empty array: []

Output ONLY valid JSON, no markdown fences, no explanation.