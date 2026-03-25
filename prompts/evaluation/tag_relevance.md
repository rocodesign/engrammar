---
name: tag-relevance-evaluation-v2
description: >
  Evaluate engram relevance and application during a session.
  Scores both direct application (acted on) and topical relevance.
goal: >
  Build richer signal for tag-based relevance filtering — distinguish
  between engrams that were applied, relevant but not applied, and irrelevant.
variables:
  - repo
  - env_tags
  - engrams_block
  - transcript
output_format: JSON array of {engram_id, action, found, relevance, tag_scores}
used_by:
  - benchmark/run_eval_benchmark.py (--attribution mode)
---
You are evaluating whether engrams shown during a Claude Code session were relevant and/or applied.

Each engram was shown to the assistant during the session. Judge TWO dimensions:
1. **Applied**: Was the engram's specific advice followed? (requires transcript evidence)
2. **Relevant**: Was the engram's topic pertinent to the session's work? (topical match)

SCORING PROTOCOL — follow these steps for each engram:

Step 1: IDENTIFY what the engram is about — the specific advice and its domain.
Step 2: SEARCH the transcript for evidence the advice was APPLIED. Can you quote a line?
Step 3: ASSESS RELEVANCE — does the engram's topic match what the session is doing, even if the specific advice wasn't followed?

SCORING TIERS:

**Applied** (+0.5 to +1.0) — the advice was directly followed:
- You can quote a specific transcript line showing the action
- The assistant chose to follow the advice (not just executing user instructions)
- +1.0 for clear, unambiguous application; +0.5 for partial or indirect application

**Relevant** (+0.1 to +0.3) — topically useful but not directly applied:
- The session involves the same domain/tool/component the engram is about
- The engram could have been useful even if the specific advice wasn't needed
- +0.3 for directly on-topic; +0.1 for adjacent topic
- Example: a cypress testing engram during a cypress debugging session, even if the specific tip wasn't used

**Neutral** (0) — no meaningful connection:
- The engram's topic doesn't relate to the session's work
- Generic or wrong-domain engram surfaced by keyword coincidence

**Negative** (-0.3 to -1.0) — actively wrong or violated:
- The engram's advice was tried and turned out wrong
- The advice was relevant but explicitly contradicted by the session's findings

COMMON MISTAKES:
- DO NOT conflate repo match with relevance. Same repo ≠ relevant topic.
- DO NOT score "applied" without a transcript quote. If you can't quote it, it's "relevant" at best.
- DO NOT give uniform scores across all tags. Each tag must be independently justified.

Session info:
- Repository: {repo}
- Environment tags: {env_tags}

Engrams shown (ID, content tags, and text):
{engrams_block}

Session transcript excerpt:
{transcript}

For each engram, output a JSON object with these fields IN THIS EXACT ORDER:
1. "engram_id": the engram ID number
2. "action": what does this engram advise? (5-10 words)
3. "found": quote the EXACT transcript line where the advice was applied, or "NO" if not applied
4. "relevance": "applied" | "relevant" | "neutral" | "negative"
5. "tag_scores": dict of content tag → score. Use ONLY the tags shown in brackets after each engram ID.
   Do NOT invent new tag names — only score the exact tags listed for that engram.
   If an engram has no tags listed, use {{}}.
   - For "applied": +0.5 to +1.0 on tags whose domain matches the advice
   - For "relevant": +0.1 to +0.3 on matching tags
   - For "neutral": MUST be {{}}
   - For "negative": -0.3 to -1.0 on matching tags

ALL FIVE FIELDS ARE REQUIRED for every engram.

Output ONLY a valid JSON array. No markdown fences, no explanation.

Example:
[{{"engram_id": 42, "action": "run tsc --noEmit before committing", "found": "assistant: Running tsc --noEmit to check types", "relevance": "applied", "tag_scores": {{"typescript": 0.8, "ci": 0.3}}}},
 {{"engram_id": 99, "action": "export NPM_TOKEN before npm publish", "found": "NO", "relevance": "relevant", "tag_scores": {{"npm": 0.2}}}},
 {{"engram_id": 55, "action": "use Form.Input for BigInt IDs", "found": "NO", "relevance": "neutral", "tag_scores": {{}}}},
 {{"engram_id": 17, "action": "use Record<string, T> for index types", "found": "Error: this approach caused a type mismatch", "relevance": "negative", "tag_scores": {{"typescript": -0.5}}}},
 {{"engram_id": 33, "action": "run happo finalize after CI completes", "found": "NO", "relevance": "relevant", "tag_scores": {{"happo": 0.15}}}}]
