---
name: tag-relevance-evaluation
description: >
  Evaluate whether engrams shown during a session were actually applied or
  useful, scoring per environment tag.
goal: >
  Build signal for tag-based relevance filtering — identify which engrams
  are useful in which contexts.
model: sonnet
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

SCORING PROTOCOL — follow these steps IN ORDER for each engram:

Step 1: IDENTIFY THE ACTION the engram advises (e.g. "use acli jira auth", "name branch after ticket", "export NPM_TOKEN").
Step 2: SEARCH the transcript for that SPECIFIC action. Can you quote a line where it happens?
Step 3: If you CANNOT quote a specific line → score 0 with empty tag_scores. Stop here.
Step 4: If you CAN quote a line → verify the action was CAUSED by the engram, not by the user's direct instruction or a pre-existing script/skill. If the user explicitly told the assistant what to do, score 0.
Step 5: Only now assign a positive score. Score ONLY tags whose domain matches the engram's advice (NOT the session's general topic).

COMMON MISTAKES TO AVOID:
- DO NOT score positive because the project/repo matches. "This is a toptal repo" does not mean every toptal engram was applied.
- DO NOT score positive for actions that never happened. No commits = 0 for commit engrams. No push = 0 for push engrams. No tests = 0 for test engrams.
- DO NOT score tags by project context. An engram about NPM_TOKEN scores 'npm' or 'env-config', NOT 'github' or 'typescript'. An engram about branch naming scores 'git', NOT 'github'.
- DO NOT give uniform scores across all tags. Each tag must be independently justified.
- DO NOT score positive when the user drove the behavior, not the engram.

Score positively (+0.3 to +1.0) ONLY if:
- You can quote a specific transcript line showing the action
- The assistant chose to follow the advice (not just executing user instructions)
- The tag scored directly relates to the engram's domain

Score negatively (-0.3 to -1.0) if:
- The engram's advice was relevant but explicitly violated
- The engram's advice was tried and turned out wrong for this situation

Score 0 (neutral) if:
- You cannot quote a specific transcript line showing the action
- The prerequisite action never occurred in the transcript
- The action happened but was user-directed, not engram-influenced
- The topic is tangentially related but the specific advice wasn't followed

Session info:
- Repository: {repo}
- Environment tags: {env_tags}

Engrams shown (ID and text):
{engrams_block}

Session transcript excerpt:
{transcript}

For each engram, output a JSON object with these fields IN THIS EXACT ORDER:
1. "engram_id": the engram ID number
2. "action": what specific action does this engram advise? (5-10 words)
3. "found": quote the EXACT transcript line where this action occurs, or "NO" if not found
4. "tag_scores": ONLY if "found" contains a real quote — dict of relevant tag → score (-1.0 to 1.0). If "found" is "NO", MUST be {{}}.

ALL FOUR FIELDS ARE REQUIRED for every engram. Do not skip any field.

Output ONLY a valid JSON array. No markdown fences, no explanation.

Example:
[{{"engram_id": 42, "action": "run tsc --noEmit before committing", "found": "assistant: Running tsc --noEmit to check types before committing", "tag_scores": {{"typescript": 0.8}}}},
 {{"engram_id": 99, "action": "export NPM_TOKEN before retrying", "found": "NO", "tag_scores": {{}}}},
 {{"engram_id": 55, "action": "use Form.Input for BigInt IDs", "found": "NO", "tag_scores": {{}}}},
 {{"engram_id": 17, "action": "use Record<string, T> for index types", "found": "Error: Type X is not assignable to type Y", "tag_scores": {{"typescript": -0.5}}}},
 {{"engram_id": 12, "action": "name branches after Jira ticket keys", "found": "NO", "tag_scores": {{}}}}]

NOTE: Most engrams will have "found": "NO" with empty tag_scores. Expect only 1-3 per session to have real quotes.