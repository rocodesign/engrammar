---
name: facet-extraction
description: >
  Extract engrams from session facet summaries (brief_summary + friction_detail).
  Older extraction path using pre-computed session metadata rather than full transcripts.
goal: >
  Extract concrete, reusable knowledge from session friction summaries while
  filtering out generic advice and implementation details.
model: haiku
variables:
  - sessions
output_format: JSON array of {category, engram, source_sessions, scope, project_signals}
used_by:
  - extractor._call_claude_for_extraction
---
You are analyzing Claude Code session data to extract SPECIFIC, ACTIONABLE engrams.

DO NOT extract:
- Generic advice like "investigate methodically" or "ask for clarification"
- Implementation details about specific functions/code internals (e.g. "function X has a gap" or "module Y does Z internally")
- Bug descriptions or one-time fixes that won't recur
- One-off data model quirks, API field mappings, or component-specific behaviors that only matter for a single task (e.g., "field X is empty, use field Y instead")

Reusability test: would knowing this save time in a DIFFERENT task in the same project? If it only helps when repeating the exact same task, skip it.

DO extract concrete, reusable knowledge like:
- "Use mcp__plugin_playwright_playwright__browser_navigate to open URLs in the browser, not Bash commands"
- "Figma MCP server must be connected before starting UI implementation — test with a simple figma tool call first"
- "Branch naming convention: taps-NUMBER (lowercase), not TEAM-NUMBER or feature/taps-NUMBER"
- "Never use inline styles in this codebase — use CSS classes or Tailwind component props"
- "PR descriptions: max 50 words, no co-authored-by lines, no file-by-file changelog"

Each engram should be a rule or pattern that saves time if known in advance — not a description of what happened.

Here are the session summaries and friction details:

{sessions}

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
- "source_sessions": list of session IDs this was derived from
- "scope": "general" if the engram applies to any project, or "project-specific" if it only applies to a particular project/tool/framework
- "project_signals": list of project/tool names when scope is "project-specific" (e.g. ["Acme", "TEAM", "Tailwind", "Figma MCP", "Playwright"]). Empty list when scope is "general".

Output ONLY valid JSON, no markdown fences, no explanation.