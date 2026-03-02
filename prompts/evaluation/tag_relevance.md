---
name: tag-relevance-evaluation
description: >
  Evaluate whether engrams shown during a session were actually applied or
  useful, scoring per environment tag.
goal: >
  Build signal for tag-based relevance filtering — identify which engrams
  are useful in which contexts.
model: haiku
variables:
  - repo
  - env_tags
  - engrams_block
  - transcript
output_format: JSON array of {engram_id, tag_scores, reason?}
used_by:
  - evaluator._call_claude_for_evaluation
---
You are evaluating whether engrams were actually applied or useful during a Claude Code session.

Each engram was shown to the assistant during the session. Your job is to determine
whether each engram's advice was ACTED ON — not whether it matches the session's topic.

IMPORTANT: An engram about git conventions is relevant in ANY project if the user did git
operations. An engram about testing is relevant if tests were run, regardless of language.
Judge by "was the advice applied?" not "does it match the tech stack?"

Score positively if:
- The user or assistant explicitly followed the engram's advice
- The user referenced or requested something the engram covers
- The engram prevented a mistake (even if not explicitly mentioned)

Score negatively ONLY if:
- The engram was actively wrong or misleading for this specific situation
- The engram's advice contradicts what was actually needed

Score 0 (neutral) if:
- The engram wasn't relevant to any action taken in the session
- The topic simply didn't come up

Session info:
- Repository: {repo}
- Environment tags: {env_tags}

Engrams shown (ID and text):
{engrams_block}

Session transcript excerpt:
{transcript}

For each engram, output a JSON object with:
- "engram_id": the engram ID number
- "tag_scores": dict mapping each relevant env tag to a score from -1.0 to 1.0
  (-1.0 = actively wrong/misleading, 0 = not acted on, 1.0 = clearly applied)
- "reason": optional brief explanation (only for negative scores)

Output ONLY a valid JSON array. No markdown fences, no explanation.

Example output:
[{{"engram_id": 42, "tag_scores": {{"typescript": 0.9, "frontend": 0.6}}}},
 {{"engram_id": 17, "tag_scores": {{"typescript": -0.5}}, "reason": "advice was wrong here"}}]