---
name: tag-relevance-evaluation-v3
description: >
  Evaluate engram usefulness during a session with a simple score.
  Tag attribution is handled separately by the scoring pipeline.
goal: >
  Get a clean usefulness signal per engram — the pipeline distributes
  the score to tags based on which tags triggered the search match.
variables:
  - repo
  - env_tags
  - engrams_block
  - transcript
output_format: JSON array of {engram_id, action, found, score}
used_by:
  - benchmark/run_eval_benchmark.py (--attribution mode)
---
You are evaluating whether engrams shown during a Claude Code session were useful.

Each engram was shown to the assistant during the session. Your job is to judge how useful each engram was — not which tags are relevant (that's handled separately).

SCORING PROTOCOL — follow these steps for each engram:

Step 1: IDENTIFY what the engram advises.
Step 2: SEARCH the transcript for evidence the advice was APPLIED or RELEVANT. Can you quote a line?
Step 3: SCORE on a -3 to +3 scale.

SCORING SCALE:

**+3** — advice was clearly applied and made a difference. You can quote the exact line.
**+2** — advice was applied but indirectly or partially.
**+1** — engram was topically relevant to the session's work, even if not directly applied.
**0** — no meaningful connection to the session.
**-1** — engram was shown but its topic doesn't match the session. Noise.
**-2** — advice was tried and turned out to be wrong or unhelpful.
**-3** — advice was actively harmful — it caused errors, wasted time, or contradicted correct findings.

RULES:
- DO NOT conflate repo match with relevance. Same repo ≠ useful engram.
- Scores of +2 or +3 REQUIRE a transcript quote in "found". If you can't quote it, cap at +1.
- Be honest about 0 and negative scores — not every engram is useful.

Session info:
- Repository: {repo}
- Environment tags: {env_tags}

Engrams shown during this session:
{engrams_block}

Session transcript excerpt:
{transcript}

For each engram, output a JSON object with these fields IN THIS EXACT ORDER:
1. "engram_id": the engram ID number
2. "action": what does this engram advise? (5-10 words)
3. "found": quote the EXACT transcript line showing application, or "NO"
4. "score": integer from -3 to +3

ALL FOUR FIELDS ARE REQUIRED for every engram.

Output ONLY a valid JSON array. No markdown fences, no explanation.

Example:
[{{"engram_id": 42, "action": "run tsc --noEmit before committing", "found": "assistant: Running tsc --noEmit to check types", "score": 3}},
 {{"engram_id": 99, "action": "export NPM_TOKEN before npm publish", "found": "NO", "score": 1}},
 {{"engram_id": 55, "action": "use Form.Input for BigInt IDs", "found": "NO", "score": 0}},
 {{"engram_id": 17, "action": "use Record<string, T> for index types", "found": "Error: this approach caused a type mismatch", "score": -2}},
 {{"engram_id": 33, "action": "run happo finalize after CI completes", "found": "NO", "score": -1}}]
