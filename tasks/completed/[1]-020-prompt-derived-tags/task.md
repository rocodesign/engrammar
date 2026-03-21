# Task: Extract tags from user prompt for dynamic content tag affinity

- Priority: High (highest)
- Complexity: C2
- Status: Completed
- Depends on: #039 (`engram_tags` table must exist, env tags dropped from scoring)
- Completed: 2026-03-20

## What shipped

- Tag vocab index: `build_tag_vocab_index()` in embeddings.py, stores `tag_vocab_embeddings.npy` + `tag_vocab_labels.json`
- Prompt tag detection: `detect_prompt_tags()` in `src/search/prompt_tags.py`
- Content tag affinity scoring: engine.py section 3.6, prompt-derived tags vs per-engram content tags
- Config: `weight_content_tag`, `weight_feedback`, `prompt_tag_top_k`, `prompt_tag_threshold`
- Vocab index built during setup/rebuild CLI
- Backfill command: `engrammar backfill-tags --llm` for cold start

## Remaining refinement (not blocking close)

- **Feedback prior not yet prompt-contextual**: engine.py:168 computes feedback from all of an engram's content tags (generic prior), not keyed by prompt-derived tags as described below. This will matter once content tag relevance data accumulates from evaluation.
- **Repo prior is fixed boost/penalty**, not a normalized scoring component. Overlaps with #018 (scoring normalization).

## Problem

Content tags (introduced by #039) capture what each engram is *about*, but search doesn't yet use them for ranking. A user asking "commit this change" gets no `git` signal, and "cypress tests" in a repo without Cypress gets no `testing` affinity. The search is blind to task intent.

## Approach: Vector-based prompt→content tag matching

Use vector similarity to discover which content tags are relevant to the user's prompt. This is self-maintaining — new tags added to engrams automatically become discoverable without updating any mappings.

### 1. Content tag vocabulary index

Build a vocabulary-level index: one embedding per unique content tag (e.g. "testing", "forms", "modal") from the `engram_tags` table.

- **Storage**: `tag_vocab_embeddings.npy` + `tag_vocab_labels.json` alongside existing index files
- **Source**: `SELECT DISTINCT tag FROM engram_tags` — embed each unique label once
- **Vocab hygiene**: Only include tags that appear on >= 2 engrams (configurable `min_tag_frequency`). One-off LLM label noise from extraction should not enter the vocabulary. Query: `SELECT tag FROM engram_tags GROUP BY tag HAVING COUNT(DISTINCT engram_id) >= 2`
- **Tag prototypes** (enhancement over bare label embedding): Single-word labels like "forms" or "state" are noisy in embedding space. A stronger representation is a **tag prototype** — the centroid of engram text embeddings for all engrams carrying that tag. Prompt-to-tag matching compares the query embedding against these prototypes, which capture what "forms" actually means in this corpus. MVP starts with bare label embeddings; upgrade to prototypes if precision is insufficient.
- **Lifecycle**: Rebuilt during `rebuild_index` — new content tags from extraction become searchable after next rebuild
- **Self-maintaining**: No manual mapping updates needed

### 2. Prompt → content tag matching

For any search query, embed the prompt and compare against the content tag vocab index via cosine similarity. Take top-k tags above a configurable threshold.

- Example: "let's write tests for blablaModal" → `["testing", "jest", "modal", "forms"]`
- Tags like "mocha" that aren't in top-k still benefit indirectly — engrams with content tag `"mocha"` are close to `"testing"` in embedding space

### 3. Scoring model

After #039, the scoring model has no environment-tag channel. Content tag affinity is the only tag-based signal:

```
final_score = w_semantic * semantic_score
            + w_content  * content_tag_affinity    # prompt-derived tags vs engram content tags
            + w_repo     * repo_prior              # from engram_repo_stats (implemented in #039)
            + w_feedback * feedback_prior           # from engram_tag_relevance eval signal
```

Each feature does one job:
- **semantic_score**: RRF fusion of vector + BM25 retrieval. Answers "is this engram textually relevant?"
- **content_tag_affinity**: prompt-derived content tags vs engram's content tags from `engram_tags`. Answers "is this engram about what the user is doing right now?"
- **repo_prior**: match history from `engram_repo_stats`. Answers "has this engram been useful in this repo before?"
- **feedback_prior**: evaluation signal from `engram_tag_relevance`, **keyed by the current prompt-derived content tags**. Looks up relevance scores for the intersection of prompt-derived tags and the engram's stored content tags. Answers "has this engram been useful when *this topic* was active?" — a contextual signal, not a generic popularity score. If no prompt-derived tags are available (empty query), falls back to overall average across all the engram's content tag relevance scores. Note: current RELEVANCE_WEIGHT (0.10) has minimal practical impact (EG#224); the new content-tag keying should be paired with a higher weight (0.20+) to be effective.

Weights are configurable in `config.json` (e.g. `weight_semantic: 0.55, weight_content_tag: 0.25, weight_repo: 0.10, weight_feedback: 0.10`).

**Normalization**: All components must be on comparable 0-1 scales before weighting. Cosine similarity is [-1, 1]; use `(sim + 1) / 2` to map to [0, 1]. Repo prior and feedback prior need their own normalization (e.g. sigmoid of match count, or min-max over result set). Document the chosen mappings explicitly so tuning is tractable.

### 4. Content tag affinity computation

For each candidate engram, compute content tag affinity:

1. Retrieve engram's content tags from `engram_tags`
2. Embed the content tag set (join tags into string, embed) — or use precomputed per-engram content tag embeddings if index exists
3. Compare against the prompt-derived content tag embedding via cosine similarity

If an engram has no content tags, its content_tag_affinity is 0.0 (neutral — doesn't penalize, just gets no boost).

### 5. Search signature

```python
def search(query, ..., extra_tags=None, cwd=None):
```

`search()` handles prompt→tag extraction internally (it already has the query). Callers don't need to change. `extra_tags` is available if callers ever want to inject additional content tags.

### 6. Configurable parameters

- `prompt_tag_top_k`: number of tags to extract from prompt (default TBD, needs testing)
- `prompt_tag_threshold`: minimum cosine similarity for prompt→tag match (default TBD, needs testing)
- `weight_semantic`, `weight_content_tag`, `weight_repo`, `weight_feedback`: scoring blend weights
- `min_tag_frequency`: minimum engram count for tag to enter vocabulary (default 2)

## Constraints

- Prompt tags affect ONLY content tag affinity scoring — soft rerank signal
- Prompt tags do NOT affect `enforce_prerequisites` — hard constraints (repos, paths, os, mcp_servers) are in `prerequisites` JSON
- Tag vocab index is built from `engram_tags` only (no environment tags exist in the system after #039)

## Files

- `src/search/engine.py` — prompt→tag extraction inside `search()`, content tag affinity scoring, four-feature blend
- `src/core/embeddings.py` — content tag vocab index build/load from `engram_tags`
- `src/search/tag_detectors.py` or new module — `detect_prompt_tags(query)` using content tag vocab index

## Validation

- Search for "commit this change" from engrammar repo → git convention engrams should rank higher than without prompt tags
- Search for "write a cypress test" from a repo without cypress → testing engrams should get affinity boost
- Search for "let's write tests for blablaModal" → should find testing + frontend + modal related engrams
- Search for "fix the rendering bug" → should NOT over-boost random testing engrams (threshold filters noise)
- Verify tag vocab index rebuilds correctly and includes only tags with frequency >= 2
- **Pinned engrams**: verify pinned engrams still pass hard constraint checks via `prerequisites` (repos, paths, os, mcp_servers). After #039 removed `check_tag_prerequisites()` from daemon, only structural checks remain. Verify this transition doesn't change which pinned engrams surface.
- **Repo prior**: verify the repo prior from `engram_repo_stats` provides equivalent or better same-repo boosting compared to the old `repo:*` tag matching
- Compare injection quality in a real session before/after
