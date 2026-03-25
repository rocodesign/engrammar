---
name: transcript-extraction-v7
description: >
  Extract engrams from full conversation transcripts — reusable knowledge about
  coding practices, library quirks, project patterns, and system integration insights.
  v7: v6's targeted rejection + consolidation instruction (merge related findings
  about the same library/tool into fewer, richer engrams) + outsider clarity test.
goal: >
  Maximize recall of durable knowledge while producing fewer, higher-quality engrams
  through consolidation and clarity requirements.
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
3. **Coding practices**: Patterns for error handling, testing strategies, API design, or code organization that worked well or were explicitly preferred
4. **Library/framework quirks**: A component, hook, library, or tool behaved unexpectedly or has non-obvious usage patterns
5. **Project patterns**: Durable project conventions, naming rules, file organization rules
6. **System integration insights**: Combining tools/services required a non-obvious configuration, ordering, or workaround
7. **Debugging insights**: Only when the fix generalizes beyond the exact page, route, dataset, or record being debugged
8. **User directives**: User states a persistent rule ("always", "never", "make sure", "in this project we...")
9. **Conventions revealed**: User shared a project/team rule the assistant didn't know

## Consolidation rule

If the transcript reveals multiple related gotchas about the same library, tool, or pattern — combine them into one engram that covers the key points. Prefer 1 rich engram over 3 thin ones about the same topic.

Example: if the transcript reveals that happo rejects Storybook 8, that happo-cypress is incompatible with Cypress 13, and that the migration requires both task and command registration — produce one consolidated engram:
"When migrating happo for Cypress 13: (1) use the unified `happo` package instead of `happo-cypress`, (2) register both the Node-side task in cypress.config and the browser-side command in support/commands, (3) happo v6+ rejects Storybook 8 so use happo.io for Storybook integration"

## Clarity rule

Write every engram so that someone who was NOT in this session can understand it. Lead with the general pattern, then give the specific example.

Bad: "Do not rename output field names in LLM extraction prompts"
Good: "When an LLM returns structured JSON, the field names in the output schema are a contract with your parsing code — renaming them breaks the parser. In this project, the extraction prompt's output fields (category, engram, source_sessions) must match what extractor.py expects."

Bad: "Use Form.TagSelector not plain TagSelector"
Good: "In picasso-forms, always use the Form.* wrapped version of input components (Form.Select, Form.TagSelector) — the unwrapped Picasso components don't participate in form validation, dirty tracking, or error display."

## Targeted rejection rules

Reject if ANY of these specific patterns applies:

### A. Internal implementation details
How the project's own code currently works — function behavior, module wiring, config plumbing, test setup. The code is the source of truth.
- "find_similar_engram only queries active engrams (WHERE deprecated = 0)"
- "New modules under src/ must be registered in conftest.py"

### B. Architecture and algorithm descriptions
Scoring formulas, embedding properties, system design. These are documentation.
- "BGE embeddings for short tags have ~0.55-0.65 baseline cosine similarity"
- "Normalizing RRF scores by dividing by max makes thresholds meaningless"

### C. One-time investigation results
Findings from debugging one specific problem that won't recur.
- "Vector similarity retrieval has a cold-start problem with empty indices"
- "High-frequency tags dilute signal — apply IDF weighting"

### D. Design decisions
Why a design choice was made, already encoded in the code.
- "For dev-only tools, prefer clean-cut renames"
- "LLM scope classification is too unreliable for hard filtering"

## What NOT to extract

- Task instructions, summaries, generic advice
- One-off data mappings, benchmark results, route maps
- Over-specific references (file paths, line numbers, exact values)
- Implementation logs (what was just built/refactored)

## Quality bar

**The key test**: would a future assistant working on a *different* task benefit from knowing this?

**Actionability**: every engram should tell a future session what to do or avoid.

**Outsider test**: could someone who has never seen this codebase understand the engram?

## Examples

Good engrams:
- "The `sortable` prop expects a comparator function, not a boolean — passing `true` silently disables sorting"
- "When mocking the router in tests, also mock useSearchParams — it throws outside RouterProvider"
- "In picasso-forms, always use Form.* wrapped components (Form.Select, Form.TagSelector) — unwrapped Picasso components don't participate in form validation or error display"
- "Schema migrations must be backward-compatible during rolling deploys — add new columns as nullable first"

Bad engrams:
- "The extractor falls back to env tags when relevant_tags is empty" (A: internal implementation)
- "BGE embeddings have ~0.55 baseline similarity for short strings" (B: algorithm property)
- "Rebuild the vocab index after each backfill batch" (C: investigation result)
- "LLM scope classification can't reliably gate engrams" (D: design decision)
{existing_instructions}{existing_tags_hint}
Environment tags detected for this session: {env_tags}

Session transcript:
{transcript}

Output a JSON array of objects, each with:
- "category": hierarchical path — "development/frontend", "development/testing", "tools/<name>", "workflow/<area>", "general/<topic>". Be specific.
- "engram": the concrete rule (1-2 sentences max). Lead with the general pattern, then the specific example.
- "source_sessions": ["{session_id}"]
- "project_signals": project/tool names mentioned in the engram (e.g. ["nx", "jest"]), else []
- "relevant_tags": (deprecated) subset of env tags the engram is about. Generic advice = [].
- "content_tags": 1-3 short topic labels. Lowercase, specific, domain/tool/concept level.

If no engrams are worth extracting, output an empty array: []

Output ONLY valid JSON, no markdown fences, no explanation.
