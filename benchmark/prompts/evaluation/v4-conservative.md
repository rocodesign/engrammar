---
name: tag-relevance-evaluation-v4
description: >
  Evaluate whether shown engrams were applied, specifically relevant, neutral,
  or contradicted. Optimized to reduce Sonnet overcalling positives.
goal: >
  Produce conservative, high-precision relevance labels for learning.
model: sonnet
variables:
  - repo
  - env_tags
  - engrams_block
  - transcript
output_format: JSON array of {engram_id, action, found, relevance, tag_scores}
---

You are evaluating whether engrams shown during a Claude Code session were actually used.

Your default label is NEUTRAL.
Only upgrade to RELEVANT or APPLIED when the transcript contains concrete evidence.

Judge FOUR labels:
- "applied" = the engram's advice directly changed what the assistant did or decided
- "relevant" = the session worked on the same specific problem, but the advice was not clearly used
- "neutral" = no specific evidence of use or need
- "negative" = the engram is contradicted, stale, wrong, or the session showed the advice should NOT be followed here

STRICT DECISION RULES

1. APPLIED requires all of these:
- You can quote an exact transcript line
- The quote shows the engram's specific advice being used, not merely discussed or observed
- The assistant made a decision, plan, code change, or diagnosis because of that advice

2. RELEVANT requires all of these:
- The session is working on the same specific issue, decision, failure mode, or mechanism as the engram
- The match is narrower than "same repo", "same subsystem", or "same general topic"
- There is not enough evidence for APPLIED

3. NEUTRAL if any of these are true:
- The transcript only confirms the engram is factually true
- The transcript merely inspects code that already implements the idea
- The topic is only adjacent or shares keywords
- The transcript discusses the same broad area but not the same concrete problem
- You are unsure between neutral and relevant → choose neutral
- You are unsure between relevant and applied → choose relevant

4. NEGATIVE if any of these are true:
- The transcript shows the engram is factually wrong, stale, or contradicted
- The session explicitly rejects the advice
- The session discovers a better rule that supersedes the engram

ANTI-GENEROSITY RULES

- Seeing an idea already present in code is NOT "applied".
- Confirming an engram's factual accuracy is NOT "applied".
- General discussion of embeddings/tags/hooks is NOT enough for relevance; the same concrete lesson must be in play.
- Same repo does NOT imply relevance.
- If the engram itself appears wrong based on the transcript, score NEGATIVE, not APPLIED.
- Most engrams should be "neutral".

CALIBRATION EXAMPLES

- If the transcript says a hook already has `_extract_narration`, that is usually RELEVANT or NEUTRAL, not APPLIED, unless the session then uses that fact to drive a change.
- If the transcript discusses cosine similarity in general, that is not enough for an engram about short-tag baseline noise or gap filtering unless those exact failure modes are discussed.
- If the transcript shows the engram's claim is false, mark NEGATIVE even if the same subsystem is being discussed.

Session info:
- Repository: {repo}
- Environment tags: {env_tags}

Engrams shown (ID and text):
{engrams_block}

Session transcript excerpt:
{transcript}

For each engram, output a JSON object with these fields IN THIS EXACT ORDER:
1. "engram_id"
2. "action" — 5-10 words describing the specific advice
3. "found" — exact quote showing use/contradiction, or "NO"
4. "relevance" — "applied" | "relevant" | "neutral" | "negative"
5. "tag_scores"
   - "applied": +0.5 to +1.0
   - "relevant": +0.1 to +0.25
   - "neutral": {{}}
   - "negative": -0.3 to -1.0

Tag scoring rules:
- Score only tags directly tied to the engram's domain
- Never score repo/context tags just because the session happened there
- Use at most 1-2 tags unless the transcript clearly justifies more

Output ONLY a valid JSON array.
