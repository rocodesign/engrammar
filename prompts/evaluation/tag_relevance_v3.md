---
name: tag-relevance-evaluation-v3
description: >
  Evaluate engram relevance and application during a session.
  Tighter "applied" gate with causality check, keeps "relevant" tier.
goal: >
  Build richer signal for tag-based relevance filtering with fewer
  false positives on the "applied" tier.
model: haiku
variables:
  - repo
  - env_tags
  - engrams_block
  - transcript
output_format: JSON array of {engram_id, action, found, relevance, tag_scores}
used_by:
  - evaluator._call_claude_for_evaluation (production)
  - benchmark/run_eval_benchmark.py (--attribution mode)
---
You are evaluating whether engrams shown during a Claude Code session were relevant and/or applied.

Judge TWO dimensions for each engram:
1. **Applied**: The engram's specific advice CHANGED what the assistant did.
2. **Relevant**: The engram's topic matches the session's work.

SCORING TIERS:

**Applied** (+0.5 to +1.0) — the advice caused a specific action:
- The assistant performed the engram's recommended action
- The action would NOT have happened without the engram (causality test)
- You can point to a specific transcript line showing the action
- Observing or discussing existing code that matches the engram does NOT count — the engram must have INFLUENCED a decision
- +1.0 clear causation; +0.5 likely influenced

**Relevant** (+0.1 to +0.3) — topically on-point but not directly applied:
- The session works in the same domain/tool/component the engram covers
- The engram's knowledge could have been useful even if not explicitly followed
- +0.3 directly on-topic; +0.1 adjacent topic

**Neutral** (0) — no meaningful connection:
- Different domain, wrong tool, or only superficial vocabulary overlap
- Sharing words like "similarity" or "testing" is NOT enough — the SPECIFIC problem must match

**Negative** (-0.3 to -1.0) — actively wrong in this context:
- The advice was tried and failed, or contradicted by session findings

CAUSALITY MISTAKES TO AVOID:
- "The code already does X" is NOT the engram being applied — it's the code pre-existing
- Finding a grep/read that confirms the engram's claim is NOT application — it's verification
- The assistant discussing the same topic is NOT application — it's coincidence
- Sharing technical vocabulary (cosine similarity, embedding, threshold) across DIFFERENT problems is NOT relevance

Session info:
- Repository: {repo}
- Environment tags: {env_tags}

Engrams shown:
{engrams_block}

Session transcript:
{transcript}

For each engram, output JSON with these fields:
1. "engram_id": the ID number
2. "action": what the engram advises (5-10 words)
3. "found": exact transcript quote where the advice was APPLIED, or "NO"
4. "relevance": "applied" | "relevant" | "neutral" | "negative"
5. "tag_scores": content tag → score dict. Empty {{}} for "neutral".

Output ONLY a valid JSON array.

Example:
[{{"engram_id": 42, "action": "run tsc --noEmit before committing", "found": "assistant: Running tsc --noEmit to check types", "relevance": "applied", "tag_scores": {{"typescript": 0.8}}}},
 {{"engram_id": 99, "action": "export NPM_TOKEN for npm publish", "found": "NO", "relevance": "relevant", "tag_scores": {{"npm": 0.2}}}},
 {{"engram_id": 55, "action": "use Form.Input for BigInt IDs", "found": "NO", "relevance": "neutral", "tag_scores": {{}}}},
 {{"engram_id": 17, "action": "use Record<string, T> for index types", "found": "Error: this broke the types", "relevance": "negative", "tag_scores": {{"typescript": -0.5}}}},
 {{"engram_id": 33, "action": "run happo finalize after CI", "found": "NO", "relevance": "relevant", "tag_scores": {{"happo": 0.15, "ci": 0.1}}}}]
