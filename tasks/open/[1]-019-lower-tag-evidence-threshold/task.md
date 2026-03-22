# Task: Lower tag relevance evidence threshold

- Priority: High
- Complexity: C1
- Status: Open

## Problem

The tag relevance filter in both `hooks/on_session_start.py:62` and `src/search/engine.py:167` requires **3+ evaluations** before filtering out negatively-scored engrams. This means new or rarely-evaluated engrams pass through freely and generate noise for multiple sessions before the system learns to suppress them.

Combined with the conservative threshold of `avg_score < -0.1`, the system is very slow to learn from negative feedback.

## Fix

1. Lower `MIN_EVALS_FOR_FILTER` from 3 to 2 in `src/search/engine.py`
2. Lower the equivalent threshold in `hooks/on_session_start.py` (line 62: `total_evals >= 3`)
3. Consider also relaxing the score threshold from `-0.1` to `-0.05` so weaker negative signals still filter

## Files

- `src/search/engine.py` — `MIN_EVALS_FOR_FILTER` constant (line 167)
- `hooks/on_session_start.py` — pinned engram tag relevance check (line 62)

## Broader context: Evaluation coverage is the feedback loop bottleneck (2026-03-22)

The threshold fix above is the quick win, but the deeper problem is **evaluation coverage is sparse**. The whole feedback loop (extraction → search → injection → evaluation → filtering) is throttled by how many engrams accumulate enough evals.

### What to measure first

Before lowering thresholds, quantify the problem:
- What % of active engrams have ≥3 evals? ≥2? ≥1?
- What's the distribution of eval counts across the corpus?
- How many sessions generate audit records vs how many get evaluated?

If most engrams have 0-1 evals, lowering the threshold from 3→2 helps marginally. The real fix would be increasing evaluation throughput — either by evaluating more sessions or by generating synthetic evals from extraction context (the extractor already sees the transcript and could provide an initial relevance signal).

### Potential approaches beyond threshold lowering

1. **Threshold 3→2** (this task) — quick, safe, helps the ~N engrams that have exactly 2 evals
2. **Seed evals from extraction context** — when the extractor creates an engram from a session, that session is implicitly a positive eval for the engram's content tags. Record this as an initial eval with lower confidence weight.
3. **Batch retroactive evaluation** — run the evaluator over historical session_audit records that were never processed (check `processed_relevance_sessions` for gaps)
4. **Lower the negative threshold** from -0.1 to -0.05 — weaker negative signals start filtering sooner

### Autoresearch validation

The autoresearch pipeline can measure the impact of threshold changes indirectly: the `weight_feedback` parameter controls how much tag relevance scores affect final ranking. Sweeping `weight_feedback` at different simulated coverage levels would show whether more feedback signal actually improves composite score, or if it's noise.

## Validation

- Query eval coverage: `SELECT COUNT(*) total, SUM(CASE WHEN positive_evals + negative_evals >= 3 THEN 1 ELSE 0 END) has_3plus, SUM(CASE WHEN positive_evals + negative_evals >= 2 THEN 1 ELSE 0 END) has_2plus FROM engram_tag_relevance`
- Give negative feedback on an engram twice and verify it stops appearing in the next session
- Confirm that engrams with mixed feedback (1 positive, 1 negative) are NOT filtered (avg ~0, above threshold)
