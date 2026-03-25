---
name: transcript-extraction-v6
description: >
  Extract engrams from full conversation transcripts — reusable knowledge about
  coding practices, library quirks, project patterns, and system integration insights.
  v6: v5's recall-friendly categories + targeted rejection for the 4 patterns that
  produce bad engrams (internal implementation, architecture descriptions,
  one-time investigation results, design decisions).
goal: >
  Maximize recall of durable, actionable knowledge while using targeted rejection
  rules (not blanket conservatism) to filter the specific categories of bad engrams
  identified in benchmark analysis.
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
5. **Project patterns**: Durable project conventions, naming rules, file organization rules that will matter across many tasks → capture the pattern
6. **System integration insights**: When combining tools/services, something required a non-obvious configuration, ordering, or workaround → capture the integration requirement
7. **Debugging insights**: Only when the fix generalizes beyond the exact page, route, dataset, or record being debugged
8. **User directives**: User states a persistent rule ("always", "never", "make sure", "in this project we...") → capture it
9. **Conventions revealed**: User shared a project/team rule the assistant didn't know → capture the rule

## Targeted rejection rules

Before including a candidate, check against these specific bad-engram patterns. Reject if ANY applies:

### A. Internal implementation details
Reject engrams that describe **how the project's own code currently works** — function behavior, module relationships, config plumbing, test setup. These are documentation, not reusable gotchas. They become stale after any refactor.

Examples to reject:
- "find_similar_engram only queries active engrams (WHERE deprecated = 0)"
- "The extractor falls back to full session env tags when relevant_tags is empty"
- "New modules under src/ must be registered in conftest.py with their src.* prefix"
- "The daemon caches Python modules at startup — restart after deploying"

The test: **is this about how the code you're currently looking at is wired together?** If yes, reject. The code itself is the source of truth.

### B. Architecture and algorithm descriptions
Reject engrams that describe **scoring formulas, algorithm properties, embedding behavior, or system design**. These are architecture docs, not actionable rules for a future task.

Examples to reject:
- "BGE embeddings for short tags have ~0.55-0.65 baseline cosine similarity"
- "Normalizing RRF scores by dividing by max makes the top result always 1.0"
- "Embedding joined bag-of-tags strings blurs per-tag signal"
- "The blend scoring formula uses w_semantic * rrf_norm + w_tag * tag_norm"

The test: **does this describe a property of a system, or does it tell you what to do?** Properties are docs; actions are engrams.

### C. One-time investigation results
Reject engrams that capture **findings from debugging one specific problem** that won't recur in the same form.

Examples to reject:
- "Vector similarity retrieval has a cold-start problem with empty indices"
- "When backfilling content tags in batches, rebuild the vocab index after each batch"
- "High-frequency tags like 'prompts', 'workflow' dilute signal — apply IDF weighting"

The test: **is this a finding from investigating one specific issue, or a gotcha that will bite someone again?** Findings are logs; gotchas are engrams.

### D. Design decisions and preferences
Reject engrams that record **why a design choice was made** rather than a reusable rule.

Examples to reject:
- "For dev-only tools, prefer clean-cut renames over backward-compatible migrations"
- "LLM-classified scope is too unreliable to use as a hard filter gate"
- "Use aggressive retrieval thresholds for automated injection, lenient for interactive"

The test: **would someone make this mistake again, or is this a one-time decision already encoded in the code?**

## What NOT to extract

- Task instructions ("do X", "build Y") — requests, not learnings
- Summaries of what was built or discussed
- Generic advice (validate inputs, write tests, check existing code first)
- One-off data mappings only useful for one specific task
- Benchmark results, scores, or investigation findings from a specific point in time
- Over-specific references — file paths, line numbers, exact constant values

## Quality bar

**The key test**: would a future assistant working on a *different* task in this project benefit from knowing this?

Passes: library quirks, framework gotchas, durable project conventions, reusable debugging patterns, integration requirements, user preferences that apply broadly.

Fails: how the code is currently wired, what an algorithm does, what one investigation found, why one design choice was made.

**Abstraction level**: write engrams that survive code refactors and feature churn. Capture the underlying reusable rule, not the surface detail.

**Actionability**: every engram should tell a future session what to do or avoid. If it only reports a property or finding, reject it.

## Examples

Good engrams (concrete, reusable, actionable):
- "The `sortable` prop expects a comparator function, not a boolean — passing `true` silently disables sorting"
- "When mocking the router in tests, also mock useSearchParams — it throws outside RouterProvider"
- "pytest fixtures sharing a DB connection across tests cause flaky failures — use fresh connections per test or transaction rollback"
- "When subprocess calls an external CLI from Python, pass `stdin=subprocess.DEVNULL` to avoid hangs"
- "Use `path == base or path.startswith(base + os.sep)` for directory containment checks — bare `startswith` produces false positives"
- "Schema migrations must be backward-compatible during rolling deploys — add new columns as nullable first"

Bad engrams (reject these — each labeled with which rejection rule applies):
- "Rebuild similarity index after each batch" (task instruction)
- "Before building a component, check if one exists" (generic advice)
- "The extractor falls back to env tags when relevant_tags is empty" (**A**: internal implementation)
- "BGE embeddings for short strings have ~0.55 baseline cosine similarity" (**B**: algorithm property)
- "Use config X with model Y for evaluation — it scored 37% yield" (**C**: investigation result)
- "LLM scope classification can't reliably gate project-specific engrams" (**D**: design decision)
- "We removed the scope field and updated the tests" (implementation log)
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
