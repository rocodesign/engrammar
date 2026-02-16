# Evaluation & Tag Relevance Scoring

How Engrammar learns which lessons are relevant in which contexts.

## Overview

The evaluation pipeline runs after each Claude Code session:

```
Session End
  → Record shown lessons + env tags (session_audit)
  → Evaluator reads transcript + shown lessons
  → Haiku judges relevance per lesson
  → Tag relevance scores updated (EMA)
  → Scores influence future search results
```

## Pipeline

### 1. Audit Recording (session end hook)

When a session ends, we record:
- Which lessons were shown (via `session_shown_lessons`)
- The environment tags at the time
- The repo name
- Path to the session transcript (if available)

Stored in `session_audit` table.

### 2. Evaluation (evaluator.py)

The evaluator processes unprocessed audit sessions:

```bash
engrammar evaluate          # process pending sessions
engrammar evaluate --limit 5  # process up to 5
```

For each session, Haiku reads the transcript and judges whether each shown lesson was relevant. Returns a raw score per lesson.

### 3. Tag Relevance Update (db.py)

Raw scores are applied to **per-tag** relevance using EMA (Exponential Moving Average):

```
new_score = old_score * (1 - ALPHA) + raw_score * ALPHA * weight
```

Constants:
- `EMA_ALPHA = 0.3` — how fast scores adapt to new signal
- `SCORE_CLAMP = (-3.0, 3.0)` — bounds to prevent runaway scores
- `weight = 1.0` for evaluator, `2.0` for direct MCP feedback

## Tag Relevance Scores

### Database Table

```sql
CREATE TABLE lesson_tag_relevance (
    lesson_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    score REAL DEFAULT 0.0,
    positive_evals INTEGER DEFAULT 0,
    negative_evals INTEGER DEFAULT 0,
    last_evaluated TEXT,
    PRIMARY KEY (lesson_id, tag)
);
```

### Reading Scores

```
engrammar log --sort score
```

Each lesson shows per-tag scores:

```
Tags:
  acme       +0.000  (+1/-0)
  frontend     +0.000  (+0/-0)
  python       -0.283  (+0/-148)
  github       -0.584  (+0/-197)
```

Format: `tag  score  (+positive_evals/-negative_evals)`

- **score**: EMA-smoothed relevance. Positive = relevant in that context, negative = not relevant.
- **positive_evals**: times the evaluator judged this lesson relevant when shown with this tag
- **negative_evals**: times judged irrelevant

### Score Convergence

EMA means the score reflects recent signal, not a lifetime average. After many identical evaluations, the score converges:

```
After 1 negative eval:  -0.3 * 1.0 = -0.300
After 2 negative evals: -0.300 * 0.7 + -1.0 * 0.3 = -0.510
After 10 negative evals: converges toward ~ -1.0
After 100 negative evals: still ~ -1.0 (clamped at -3.0 max)
```

The eval counts keep growing but the score stabilizes. This is by design — the EMA responds to trend changes while the counts tell you confidence level.

## How Scores Affect Search

### Tag Relevance Filtering (search.py)

After RRF ranking, before returning results, search applies tag relevance:

```python
MIN_EVALS_FOR_FILTER = 3         # need evidence before filtering
NEGATIVE_SCORE_THRESHOLD = -0.1  # filter if avg below this
RELEVANCE_WEIGHT = 0.01          # boost/penalty weight
```

For each candidate lesson:
1. Compute `(avg_score, total_evals)` across current env tags
2. If `total_evals >= 3` AND `avg_score < -0.1` → **filter out**
3. Otherwise → apply score as boost: `rrf_score += (avg_score / 3.0) * 0.01`

### What Happens Per Lesson State

| State | avg_score | evals | Result |
|-------|-----------|-------|--------|
| New (no data) | 0.0 | 0 | Passes, no boost |
| Positive signal | >0 | >=3 | Passes, boosted |
| Weak negative | -0.1 to 0 | >=3 | Passes, slight penalty |
| Strong negative | <-0.1 | >=3 | **Filtered out** |
| Strong negative, low evidence | <-0.1 | <3 | Passes (exploration) |

### avg_score Calculation

`get_tag_relevance_with_evidence()` divides by **total requested tags**, not just matched rows. Missing tags count as 0.0.

Example: env tags = `["python", "github", "personal"]`, lesson has scores for `python` (-0.283) and `github` (-0.584) but not `personal`:

```
sum = -0.283 + -0.584 + 0.0 = -0.867
avg = -0.867 / 3 = -0.289
total_evals = 148 + 197 + 0 = 345
→ 345 >= 3 and -0.289 < -0.1 → FILTERED OUT
```

Same lesson with env tags = `["acme", "frontend"]`:

```
sum = 0.0 + 0.0 = 0.0
avg = 0.0 / 2 = 0.0
total_evals = 1 + 0 = 1
→ 1 < 3 → NOT ENOUGH EVIDENCE, passes through
```

## Structural vs Tag Prerequisites

Prerequisites have two roles:

### Structural Prerequisites (hard gate)
- `os`, `repos`, `paths`, `mcp_servers`
- Physical constraints — checked by `check_structural_prerequisites()`
- Always enforced in search, session start, and daemon

### Tag Prerequisites (soft, score-based)
- `tags` in prerequisites JSON
- **No longer hard-gated** in search
- Tag relevance scores handle filtering dynamically
- Lessons can appear in contexts where they weren't originally tagged, if the evaluator hasn't accumulated enough negative signal to filter them

This means a lesson with `{"tags": ["acme", "react"]}` is no longer locked to only acme+react environments. It enters the candidate pool everywhere, and the evaluator gradually learns where it's relevant.

## Auto-Pin and Tag Relevance

Two separate systems can pin lessons:

### Match-count auto-pin (db.py)
- Threshold: 15 matches for a tag subset
- Adds `tags` to prerequisites and sets `pinned=1`
- Based on how often a lesson is *shown*

### Tag-relevance auto-pin (db.py)
- Threshold: `avg_score > 0.6` with `>= 5` evals
- Sets `auto_pinned: true` in prerequisites
- Based on evaluator *quality* judgments
- Can auto-unpin if score drops below 0.2

### Pinned Lesson Filtering (session start / daemon)

Pinned lessons go through:
1. `check_structural_prerequisites()` — hard gate on os/repo/paths/mcp
2. Tag relevance check — filter if `total_evals >= 3` and `avg < -0.1`

## Debugging

### Check a lesson's tag relevance

```bash
engrammar log <id> --sort score
```

### Check pending evaluations

```bash
~/.engrammar/venv/bin/python -c "
import sys; sys.path.insert(0, '$HOME/.engrammar')
from engrammar.db import get_unprocessed_audit_sessions
print(len(get_unprocessed_audit_sessions(limit=100)))
"
```

### Force re-evaluation

Delete the processed record and re-run:

```sql
DELETE FROM processed_relevance_sessions WHERE session_id = '...';
```

Then `engrammar evaluate`.

### Why is a lesson showing/not showing?

1. Check structural prerequisites: `engrammar log <id>` → look at prerequisites
2. Check tag relevance: look at per-tag scores and eval counts
3. If `avg < -0.1` with `>= 3` evals across current env tags → filtered out
4. If no tag data → passes through (exploration)
