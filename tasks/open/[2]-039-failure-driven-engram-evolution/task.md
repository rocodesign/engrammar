# Task: Failure-Driven Engram Evolution

- Priority: Medium
- Complexity: C3
- Status: Open
- Inspired by: MetaClaw `SkillEvolver` — generates new skills from failed sessions

## Problem

Engrammar extracts engrams from all sessions equally. It has no mechanism to specifically target repeated failure patterns — sessions where the agent struggled, got corrected, or where surfaced engrams were repeatedly rated irrelevant. The current extraction prompt looks for friction moments, but it doesn't distinguish between "new friction" and "existing memory that keeps failing in deployment."

## Proposed approach

### 1. Detect failing engrams

Track engrams with consistently negative evaluation scores across multiple sessions. Criteria:

- Tag relevance EMA below threshold (e.g., < -0.2) across 3+ evaluated sessions
- Or: engram shown 5+ times but never rated positively
- Or: multiple sessions produce near-duplicate corrections around the same topic

### 2. Generate rewritten candidates

When an engram is flagged as failing:

- Collect the session transcripts where it was shown and rated negatively
- Send to LLM with the current engram text + failure evidence
- Ask for a rewritten version that addresses the failure pattern
- Optionally split one vague engram into several narrower ones

### 3. Stage before promotion

Rewritten candidates go through `#012` staging pipeline rather than immediate injection. This prevents bad rewrites from polluting the knowledge base.

### 4. Validate against held-out sessions

Use sessions that didn't trigger the rewrite as validation evidence (MAML-style support/query separation). The rewritten engram must score positively on held-out sessions before promotion.

## Relation to existing work

- `#012` (staging) — rewritten candidates use the same staging pipeline
- `#029` (extraction benchmark) — provides ground truth for measuring improvement
- `#031` (preserve eval context through dedup) — needed so failure evidence survives merges
- `#040` (engram versioning) — version bump on rewrite prevents stale evidence pollution
- `tasks/ideas/metaclaw-inspired-adaptation-loop.md` — this task implements §1 of that idea
- `tasks/ideas/metaclaw-inspired-skill-lifecycle.md` — this task implements §2 of that idea

## Implementation sketch

### New module: `src/pipeline/evolver.py`

```python
def find_failing_engrams(min_negative_sessions=3, score_threshold=-0.2):
    """Query engrams with consistently negative tag relevance scores."""

def collect_failure_evidence(engram_id, max_sessions=6):
    """Gather transcript excerpts from sessions where engram was shown and rated negatively."""

def generate_rewrite(engram_text, failure_evidence, existing_engram_names):
    """LLM call to produce rewritten candidate from failure patterns."""

def evolve_failing_engrams():
    """Main loop: find → collect → rewrite → stage."""
```

### Daemon integration

- Add as a low-priority background job in daemon queue (after extraction and evaluation)
- Only runs when extraction queue is empty (same pattern as dedup)

## Files

- `src/pipeline/evolver.py` — new module
- `src/infra/daemon.py` — add evolution job type
- `src/core/db.py` — query for failing engrams
