---
name: quality-gate-v2-gate-dedup
description: >
  Combined quality gate + dedup for post-extraction filtering.
  Receives batches of semantically similar engrams, rejects bad ones,
  and merges duplicates in a single pass.
  Based on v1-basic (91% accuracy with opus) + targeted rejection from v6 extraction
  + dedup consolidation from the dedup/system.md prompt.
model: opus
variables:
  - engrams_json
output_format: JSON with verdicts[] and merge_groups[]
used_by:
  - benchmark/run_quality_gate.py
---
You are evaluating and deduplicating engrams — short actionable lessons extracted from coding sessions. You receive a batch of semantically similar engrams. For each batch, do two things:

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

## 2. Dedup: merge true duplicates

Among the engrams you marked "keep", identify groups that express the **same core lesson** and should be merged into one.

Merge ONLY when ALL are true:
- Same core action/recommendation
- Same expected outcome or rationale
- Context constraints are compatible

Do NOT merge when:
- They are topically related but prescribe different actions
- One is broader guidance and another is a specific sub-rule
- Details conflict (commands, flags, versions, APIs)

For each merge group, produce a canonical text that:
- Is 1-2 sentences, concrete and actionable
- Generalizes across contexts when the core lesson is the same
- Preserves important specifics (commands, flags, code spans)
- Is self-contained — understandable without session context

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
