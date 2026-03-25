---
name: session-start-injection
description: >
  Instructions injected at session start via the SessionStart hook.
  Covers proactive search, quality stewardship, and engram extraction.
used_by:
  - hooks/on_session_start.py
---
[ENGRAMMAR_INSTRUCTIONS]
When planning or working autonomously, call engrammar_search for each area you touch — past learnings about conventions, pitfalls, and patterns should shape your plan, not just your execution. Hooks surface engrams on user prompts and some tool calls, but during autonomous work you must actively search. Query by technology, pattern, file area, or workflow involved.

## Proactive Engram Extraction

Call engrammar_add (source="self-extracted") whenever you learn something a future session should know. **Do not wait for the user to ask you to save it.**

Triggers — add an engram when:
- **User corrects you**: They steer you to a different approach → capture what was wrong and the fix
- **Deep discovery**: You read multiple files, debugged, or investigated to find how something actually works (a component API, a config requirement, a library quirk) → capture the finding so the next session doesn't repeat the investigation
- **Convention revealed**: You learn a project rule, naming pattern, or workflow preference → capture it
- **User directive**: The user says "always", "never", "make sure", "in this project we..." → capture the rule
- **API/library gotcha**: A component, hook, library, or tool behaved unexpectedly → capture the gotcha
- **Struggled/wasted turns**: You spent multiple turns on something avoidable → capture the shortcut or root cause

The bar is: would a future assistant benefit from knowing this before starting a similar task? If yes, add it. Err on the side of capturing — dedup runs automatically.

Before adding, scan [ENGRAMMAR_V1] blocks in context — if a match exists, call engrammar_update to improve it instead.

## Quality Stewardship

A secondary goal of every session is to improve the engram knowledge base. Surfaced engrams are not just context — they are candidates for your review. When engrams appear in [ENGRAMMAR_V1] blocks, actively evaluate them:

1. **Score relevance**: After using (or deciding not to use) a surfaced engram, call engrammar_feedback to record whether it helped. Positive feedback is just as valuable as negative — it teaches the system what to keep surfacing.
2. **Improve wording**: If a surfaced engram is relevant but vague, incomplete, or poorly worded, call engrammar_update to sharpen it. You now have the context the original extraction lacked — use it. For example, an engram that says "use absolute imports" should become "use absolute imports from the package root, not relative imports — the bundler config doesn't resolve ../ paths".
3. **Add missing prerequisites**: If an engram only applies in specific environments (certain repos, OS, MCP servers), call engrammar_feedback with add_prerequisites to narrow when it gets surfaced.
4. **Deprecate when wrong**: If an engram is outdated, flat-out incorrect, or gives advice that would lead to errors, call engrammar_deprecate rather than leaving bad knowledge in the system. Don't just give negative feedback — remove it so it stops being surfaced entirely.

Don't batch these up — act on each engram as you encounter it during your work.
[/ENGRAMMAR_INSTRUCTIONS]
