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
You are analyzing a Claude Code conversation transcript to extract engrams from FRICTION — moments where the assistant got something wrong and the user had to intervene.

ONLY extract from these patterns:
1. **User corrections**: The assistant tried approach A, then the user said "no, do B instead" or "that's wrong, use X". Capture the rule: "Do B, not A" or "Use X because Y".
2. **Repeated struggle**: The assistant spent multiple turns on something that could have been avoided. Capture the shortcut or root cause.
3. **Discovered conventions**: The user revealed a project rule the assistant didn't know (naming, architecture, workflow). Capture the rule.
4. **Tooling gotchas**: A tool or API behaved unexpectedly and required a workaround. Capture the gotcha.
5. **User-established rules**: The user states a rule or preference using directive language ("always", "never", "make sure", "don't forget", "in this project we..."). Capture the rule even without prior friction — the user is encoding knowledge they expect to persist.

CRITICAL — DO NOT extract:
- User instructions or requests ("do X", "build Y", "add Z") — these are TASKS, not engrams
- Summaries of what was built or discussed
- Generic programming advice (validate inputs, write tests, use types)
- Implementation details about specific functions
- Anything that reads like a design decision rather than a correction
- One-off data model quirks, API field mappings, or component-specific behaviors that only matter for a single task (e.g., "field X is empty, use field Y instead" or "component Z stores data in array A not field B")

The test: if the engram is something the user TOLD the assistant to do (not something the assistant got WRONG), it is NOT a engram — UNLESS the user is establishing a persistent rule using directive language.

Reusability test: would knowing this save time in a future task in the same project or similar projects? Project conventions, team workflow rules, and API/framework gotchas are reusable even if project-specific. Non-obvious API details about shared/library components (components in lib/, packages/, shared/ directories that are used across multiple features) ARE reusable — anyone using that component benefits. Only filter out details about single-use page-level code. If it only helps when repeating the exact same task, do NOT extract it.

Good examples (notice the correction/convention pattern):
- "Use cy.contains('button', 'Text') not cy.get('button').contains('Text') — the latter yields the deepest element, not the button"
- "In this monorepo, run codegen scoped to the app (nx run app:codegen), not workspace-wide"
- "PR descriptions: max 50 words, no co-authored-by lines — the assistant kept adding verbose descriptions"
- "Verify packages exist in package.json before importing — don't assume packages are installed"
- "Always use absolute imports in this project, never relative"
- "SkillTag component uses `main` boolean prop (not rating='main') to display main skills with arrow icon" (shared library component API — reusable across features)

Bad examples (these are just task summaries or one-off details):
- "Rebuild similarity index after each batch" (user instruction, not a correction)
- "Validate input at system boundaries" (generic advice)
- "Session IDs are provided by Claude infrastructure" (factual description, no friction)
- "For CITY type profiles, the location field is empty — use onsiteLocations array" (one-off data model detail, only useful for that exact component)
- "The API returns data in the 'results' key" (one-off field mapping, not a reusable pattern)
{existing_instructions}
Session transcript:
{transcript}

Output a JSON array of objects, each with:
- "category": hierarchical category path using these prefixes:
    - "development/frontend" (styling, components, react, etc.)
    - "development/backend" (APIs, databases, etc.)
    - "development/git" (branching, PRs, commits)
    - "development/testing" (test patterns, frameworks)
    - "development/architecture" (project structure, patterns)
    - "tools/<tool-name>" (figma, jira, playwright, claude-code, etc.)
    - "workflow/<area>" (communication, setup, debugging)
    - "general/<topic>" (catch-all for anything else)
  Be specific: "development/frontend/styling" not "tool-usage", "tools/playwright" not "tools/figma" for browser testing.
- "engram": the specific, concrete engram (1-2 sentences max)
- "source_sessions": ["{session_id}"]
- "scope": "general" if the engram applies broadly, or "project-specific" if it only applies to a particular project/tool
- "project_signals": list of project/tool names when scope is "project-specific". Empty list when scope is "general".

If no engrams are worth extracting, output an empty array: []

Output ONLY valid JSON, no markdown fences, no explanation.