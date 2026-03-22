---
name: tag-relevance-evaluation-v5
description: >
  Structural dual-evidence evaluation. Two separate evidence fields
  with hard rules mapping evidence to labels. Designed to prevent
  false positives through structure, not prose.
goal: >
  High-precision relevance labels via structural constraints.
model: sonnet
variables:
  - repo
  - env_tags
  - engrams_block
  - transcript
output_format: JSON array of {engram_id, action, applied_evidence, relevance_evidence, relevance, tag_scores}
used_by:
  - benchmark/run_eval_benchmark.py (--attribution mode)
---
You are evaluating engrams shown during a Claude Code session.

For each engram, collect TWO pieces of evidence independently, then apply the label rules below.

EVIDENCE FIELDS:

1. "applied_evidence" — quote a transcript line where the assistant CHANGED behavior because of this engram's advice. Valid changes:
   - A decision change ("I'll use X instead of Y")
   - A code edit implementing the advice
   - A command/tool action following the advice
   - An explicit causal statement ("because of X we should do Y")

   If none of the above: "NO"

2. "relevance_evidence" — quote a transcript line where the session works on the SAME SPECIFIC problem the engram addresses. The problem must match, not just the technology or subsystem.

   If the session doesn't touch the engram's specific problem: "NO"

LABEL RULES (apply mechanically):

- If relevance_evidence == "NO" → "neutral"
- If relevance_evidence != "NO" AND applied_evidence == "NO" → "relevant"
- If applied_evidence != "NO" → check the quote:
  - Shows a decision change, code change, command, or causal statement → "applied"
  - Shows only observation of existing code or fact confirmation → "relevant" (downgrade)
- If the transcript contradicts the engram or shows it is wrong → "negative"

SCORE RULES:
- "applied": +0.5 to +1.0 on tags matching the engram's domain
- "relevant": +0.1 to +0.25
- "neutral": {{}}
- "negative": -0.3 to -1.0

Session info:
- Repository: {repo}
- Environment tags: {env_tags}

Engrams shown:
{engrams_block}

Transcript:
{transcript}

Output a JSON array. Each object has these fields IN ORDER:
1. "engram_id"
2. "action": what the engram advises (5-10 words)
3. "applied_evidence": exact quote or "NO"
4. "relevance_evidence": exact quote or "NO"
5. "relevance": "applied" | "relevant" | "neutral" | "negative"
6. "tag_scores": content tag → score dict

Output ONLY valid JSON.
