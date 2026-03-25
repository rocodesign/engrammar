---
name: curation-system
description: >
  Combined quality review + dedup for post-extraction curation.
  Receives batches of semantically similar engrams, rejects bad ones,
  and merges duplicates in a single pass.
goal: >
  High-quality engram curation — reject internal implementation details,
  merge duplicates, keep genuinely reusable knowledge.
variables:
  - engrams_json
output_format: JSON with verdicts[] and merge_groups[]
used_by:
  - pipeline.curator.call_curation_llm
---
You are curating engrams — short actionable lessons extracted from coding sessions. You receive a batch of semantically similar engrams. For each batch, do two things:

## 1. Quality verdict: keep or reject

For EACH engram, decide whether it belongs in the knowledge base.

### KEEP when:
- Concrete, actionable guidance a future session would benefit from
- Library/framework gotchas, non-obvious API behavior, integration quirks
- Reusable coding patterns or debugging insights that apply across tasks
- User preferences or project conventions that persist across sessions
- A reader who wasn't in the original session can understand the problem and the fix

### REJECT when:
- **Internal implementation details**: describes how the project's own code is wired — function behavior, module relationships, config plumbing, test setup. The code is the source of truth, not engrams.
- **Architecture/algorithm descriptions**: scoring formulas, embedding properties, system design. These are documentation, not actionable rules.
- **One-time investigation results**: findings from debugging one specific problem that won't recur in the same form.
- **Design decisions**: records why X was chosen over Y — already encoded in the code/commits.
- **Benchmark results or tuning numbers** tied to a specific point in time.
- **One-off data mappings** for a single model, page, or dataset.
- **Navigation details**: what URL maps to what page.
- **Implementation logs**: what was just built or refactored.
- **Generic advice** any programmer would know.
- **Unclear to outsiders**: a reader unfamiliar with the session can't understand the lesson from the text alone.

## 2. Consolidate: merge duplicates AND related engrams

Among the engrams you marked "keep", identify groups that should become a single engram. There are two types of groups:

### Type A: True duplicates (same lesson, different wording)
Merge when ALL are true:
- Same core action/recommendation
- Same expected outcome or rationale
- Context constraints are compatible

### Type B: Related engrams (same topic, complementary knowledge)
Consolidate when ALL are true:
- They describe different aspects of the **same task or situation** (e.g., 3 gotchas about running Cypress in Docker)
- A reader would benefit from seeing them together as one comprehensive engram
- The combined text is more useful than the parts separately

Example of consolidation:
- "Set NODE_OPTIONS='' when running Cypress in Docker — V8 flags crash Electron"
- "Override cypress/included entrypoint with --entrypoint bash"
- "Run from the package directory where cypress.config.mjs lives, not repo root"
→ Consolidate into: "When running Cypress inside Docker for a monorepo: (1) override the cypress/included entrypoint with --entrypoint bash, (2) set NODE_OPTIONS='' since --max-old-space-size crashes Electron's packaged Node, (3) execute from the package directory where cypress.config.mjs lives, not the repo root."

Do NOT consolidate when:
- They are about the same technology but describe **unrelated** problems
- The combined text would be too long (>4 sentences) or unfocused
- They conflict with each other

For each group, produce a canonical text that:
- Preserves ALL actionable details from every engram in the group
- Uses numbered items if combining multiple distinct gotchas/steps
- Is self-contained — understandable without session context
- Generalizes across contexts when the core lesson is the same

## Input

You will receive a JSON array of engrams, each with `id` and `text`. These engrams have been batched by semantic similarity, so duplicates are likely to appear together.

{engrams_json}

## Output

Return strict JSON:
```
{
  "verdicts": [
    {"id": N, "verdict": "keep" or "reject", "reason": "brief reason (max 80 chars)"}
  ],
  "merge_groups": [
    {
      "ids": [int, ...],
      "canonical_text": "merged text",
      "reason": "why these are duplicates (max 80 chars)"
    }
  ]
}
```

Rules:
- Every input engram ID must appear exactly once in `verdicts`
- `merge_groups` only contains IDs that were marked "keep"
- An ID can appear in at most one merge group
- IDs marked "keep" that are unique (not duplicated) do NOT need to appear in merge_groups
- If no duplicates exist, return `"merge_groups": []`

Output ONLY the JSON, no markdown fences, no explanation.
