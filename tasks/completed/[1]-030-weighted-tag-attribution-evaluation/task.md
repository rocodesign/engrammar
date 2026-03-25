# Task: Weighted Tag Attribution for Evaluation

- Priority: High
- Complexity: C2
- Status: Done (2026-03-26)

## Update (2026-03-26): Completed

All remaining gaps addressed:

1. **Evaluator prompt now injects actual content tags** per engram (e.g. `[tags: jira, cli]`), so Claude scores real tags instead of inventing phantom names. Prompt explicitly says "Use ONLY the tags shown in brackets."

2. **Phantom tag pollution fixed** — evaluator code now filters `tag_scores` to only store scores for tags that exist on the engram (`engram_tags`) or are env tags (`repo:*`, `os:*`). Previously, Claude's invented tag names created phantom entries in `engram_tag_relevance`.

3. **Redundant weighted attribution removed** — with Claude scoring real tags directly, the separate `_compute_weighted_attribution` pass in the evaluator was redundant (it averaged Claude's per-tag scores then re-distributed them).

4. **MCP feedback uses prompt_tags for weighted attribution** — when no explicit `tag_scores` provided, looks up `prompt_tags` from `session_shown_engrams` for the current session and uses `_compute_weighted_attribution` to weight which content tags receive the feedback signal. Falls back to uniform if no prompt context available.

5. **Dedup-safety** — fixed in #031.

DB audit at fix time: engram #1 had 2 real content tags but 15 phantom tags with accumulated eval scores.

## Update (2026-03-25): Partially implemented

Groundwork for this task is already in the codebase:

- hooks record `prompt_tags` / `query_text` for shown engrams
- Stop writes per-engram context into `session_audit.engram_context`
- evaluator uses weighted content-tag attribution derived from prompt tags

## Problem

The evaluator was built before content tags existed. When it judges an engram as "useful" or "not useful", the verdict is distributed equally across all content tags via a blunt average:

```python
avg_signal = sum(tag_scores.values()) / len(tag_scores)
content_scores = {ct: avg_signal for ct in content_tags}
```

This means an engram with tags `[happo, typescript, frontend]` that matched a query about happo gets the same eval score on all three tags — even though `typescript` and `frontend` had nothing to do with the match. This pollutes tag relevance data with false attribution.

## Design

### 1. Store per-engram-tag similarity at search time

When an engram is shown during a session, the tag affinity step already computes a sim matrix between prompt tags and engram tags. Store the per-engram-tag best similarity in the session audit:

```python
# During search, for each shown engram:
tag_sims = {}
for engram_tag in engram_content_tags:
    best_sim = max(cosine_sim(prompt_tag_emb, engram_tag_emb) for prompt_tag in prompt_tags)
    tag_sims[engram_tag] = best_sim

# Store in session_audit alongside shown_engram_ids:
# {engram_id: 42, tag_sims: {"happo": 0.95, "typescript": 0.30, "frontend": 0.25}}
```

### 2. Shifted sigmoid attribution curve

At evaluation time, use a non-linear curve to convert tag similarity into attribution weight. Tags with high similarity get disproportionately more of the eval signal:

```python
def attribution_weight(sim, floor=0.20, ceiling=1.0):
    """Shifted sigmoid: strong matches get full signal, weak matches fade to zero."""
    if sim <= floor:
        return 0.0
    normalized = (sim - floor) / (ceiling - floor)
    return normalized ** 2
```

Curve behavior:
```
sim 0.95 → weight 0.88  (strong match → nearly full eval signal)
sim 0.80 → weight 0.56  (good match → most of the signal)
sim 0.40 → weight 0.06  (weak match → negligible signal)
sim 0.20 → weight 0.00  (natural cutoff, no attribution)
```

### 3. Apply weighted eval scores per tag

```python
eval_verdict = +0.8  # from evaluator
tag_sims = {"happo": 0.95, "typescript": 0.30, "frontend": 0.25}

for tag, sim in tag_sims.items():
    weight = attribution_weight(sim)
    tag_score = eval_verdict * weight
    # happo:      0.8 * 0.88 = +0.70  (strong signal)
    # typescript: 0.8 * 0.02 = +0.01  (negligible)
    # frontend:   0.8 * 0.00 = +0.00  (below floor, no signal)
    update_tag_relevance(engram_id, {tag: tag_score})
```

### 4. Keep repo-level scoring as-is

The existing env-tag/repo evaluation with dampened formula stays unchanged — it's a separate, weaker signal that doesn't need this precision. The weighted attribution only applies to content tag scoring.

## Why this matters

- **Feedback loop precision**: Currently RELEVANCE_WEIGHT has minimal practical impact (0.002-0.017 per query) partly because scores are diluted across irrelevant tags. Concentrated scoring on matched tags means the signal accumulates faster where it matters.
- **Faster learning**: A tag at 0.95 sim accumulates nearly full eval signal each time. After 2-3 sessions the system knows whether `happo` engrams are useful for happo queries. Currently it takes many more sessions because the signal is spread thin.
- **No false attribution**: Tags that didn't contribute to the match get no signal. `typescript` on a happo engram won't accumulate spurious positive/negative scores from happo-related queries.

## Implementation

### Stop hook changes
- Compute `tag_sims` dict during search (per shown engram)
- Add `tag_sims` to `session_audit` record (JSON field alongside `shown_engram_ids`)
- Small — 2-5 floats per engram, serialized as JSON

### Evaluator changes
- Read `tag_sims` from audit record
- Replace the `avg_signal` averaging with `attribution_weight(sim) * eval_verdict` per tag
- Fallback: if `tag_sims` not present (old audit records), use current avg behavior

### Autoresearch validation
- The `floor` parameter of the shifted sigmoid is sweepable
- Compare composite score with old uniform attribution vs new weighted attribution
- Expect stronger class_separation as feedback signal concentrates on relevant tags

## MetaClaw-inspired: Per-turn relevance scoring

MetaClaw's PRM scores **each assistant response** individually with a majority-vote process reward model, rather than evaluating the whole session as a unit. Currently engrammar evaluates engram relevance at the session level.

### Idea: Turn-level attribution

Instead of one verdict per engram per session, score relevance **per turn where the engram was active**:

- The audit already records `hook_event` and `shown_at` timestamps per engram
- The evaluator could segment the transcript by turns and ask: "Was this engram useful for the response that followed its injection?"
- Per-turn scores are then aggregated (weighted by recency or turn importance) into the session-level verdict

### Why this helps

- An engram injected at SessionStart that's useful for turn 3 but irrelevant for turns 7-15 currently gets a diluted score
- Per-turn scoring would give it a strong positive for turn 3 and neutral for the rest
- Combined with weighted tag attribution, this makes the feedback signal much more precise

### Trade-off

- More LLM calls per evaluation (one per turn-engram pair vs one per session)
- Could be approximated: only score the turn immediately following injection rather than all turns
- Consider as a future enhancement after the base weighted attribution is working

## Files

- `src/search/engine.py` — expose per-engram tag_sims in diagnostics
- `hooks/on_stop.py` — store tag_sims in session_audit
- `src/pipeline/evaluator.py` — weighted attribution in `run_evaluation_for_session()`
- `src/core/db.py` — add tag_sims column or extend shown_engram_ids JSON schema
