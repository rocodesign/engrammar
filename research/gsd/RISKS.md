# Semantic Lesson Search System -- Risks and Mitigations

## Risk 1: Latency Exceeds 50ms Budget

**Severity: HIGH | Probability: MEDIUM (30%)**

### The Risk

The 50ms end-to-end budget is tight. The breakdown:

| Component | Best Case | Worst Case | Bottleneck |
|-----------|-----------|------------|------------|
| Hook script startup (bash + jq + curl) | 5ms | 15ms | Process spawn, jq parse |
| HTTP to local server | <1ms | 2ms | TCP handshake if no keep-alive |
| Ollama embedding | 15ms | 40ms | Model not loaded (cold start), CPU fallback |
| ChromaDB query | 2ms | 8ms | Large collection, complex where clause |
| Response formatting + return | <1ms | 2ms | -- |
| **Total** | **~23ms** | **~67ms** | Ollama cold start |

The worst case (67ms) exceeds the budget. The primary risk is **Ollama model unloading**: Ollama has a model eviction policy and may unload nomic-embed-text if other models are used. The first request after eviction triggers a model load (~1-3 seconds).

### Mitigations

1. **Set Ollama `OLLAMA_KEEP_ALIVE=-1` (indefinite).** This prevents model eviction entirely. The nomic-embed-text model uses only 0.5GB, so keeping it resident is cheap. Set via `launchctl setenv OLLAMA_KEEP_ALIVE -1` or in the Ollama LaunchAgent plist.

2. **Warm ping on server startup.** The lesson search server sends a dummy embedding request to Ollama during its own startup sequence, ensuring the model is loaded before any real queries arrive.

3. **Use a compiled hook script instead of bash.** A small Go binary reading stdin, making an HTTP call, and writing to stdout avoids the bash/jq/curl overhead. Expected savings: 5-10ms. This is an optimization to pursue if latency is tight in practice.

4. **Pre-connect with HTTP keep-alive.** The FastAPI server maintains a persistent `httpx.AsyncClient` connection to Ollama, avoiding TCP handshake overhead on each request.

5. **Accept graceful degradation.** If the hook takes >50ms occasionally, the user experience impact is minimal: Claude Code shows the hook spinner briefly. The prompt is not blocked. Set the hook timeout generously (5s) and let the latency variation be absorbed.

### Monitoring

Add a `query_time_ms` field to every response from `/api/query`. The hook script can log timings to `~/.local/share/lesson-search/logs/latency.log` for analysis. Alert (log warning) if p95 exceeds 50ms over a rolling window.

---

## Risk 2: Ollama Not Running When Hook Fires

**Severity: MEDIUM | Probability: MEDIUM (25%)**

### The Risk

The UserPromptSubmit hook fires on every prompt. If Ollama is not running (crashed, not installed, killed by user), the embedding call fails and no lessons are returned. Scenarios:

- Ollama.app not installed or not started.
- Ollama crashed and its LaunchAgent is restarting it (brief window).
- User explicitly quit Ollama.
- System resource pressure caused OOM kill.

### Mitigations

1. **Silent failure in the hook script.** The hook exits 0 with no stdout on any error. The user never sees an error. Claude processes the prompt normally without lesson context. This is the critical design principle: the lesson search system is **additive only** and must never degrade the base experience.

2. **Health check with cached status.** The lesson search server checks Ollama connectivity on startup and periodically (every 60s). If Ollama is unreachable, `/api/query` returns an empty result set immediately without attempting the embedding call (~0ms instead of waiting for connection timeout).

3. **Startup dependency ordering.** The lesson search server's launchd plist includes a check: on startup, the server waits up to 10 seconds for Ollama to become reachable. If it does not, the server starts anyway in degraded mode.

4. **Fallback: pre-computed query embeddings.** For the most common query patterns, cache the embeddings locally. If Ollama is down, use the cached embedding for an approximate search. This is a future optimization, not required for v1.

### Impact Assessment

When Ollama is down, the only impact is that lessons are not injected as context. Claude Code works exactly as it does today. Users may not even notice unless they specifically look for lesson suggestions. This is acceptable.

---

## Risk 3: Embedding Model Quality for Code/Technical Content

**Severity: MEDIUM | Probability: MEDIUM (35%)**

### The Risk

nomic-embed-text v1.5 is a general-purpose text embedding model. It was trained on a broad web corpus, not specifically on programming or technical documentation. Potential failure modes:

- **Code snippets** may not embed well. A lesson about "use `NODE_OPTIONS=--max-old-space-size=4096`" might not match a query about "frontend build running out of memory."
- **Tool-specific jargon** ("rebase onto main", "squash commits", "HNSW index") may not have strong semantic representations.
- **Short lessons vs long queries** (or vice versa) can produce poor similarity scores due to length mismatch.

### Evidence

nomic-embed-text v1 scores ~55 on MTEB retrieval benchmarks, compared to mxbai-embed-large at ~64.7. This is a meaningful gap. However, MTEB benchmarks test on academic/general datasets, not on technical lessons. The actual quality for our use case needs empirical testing.

### Mitigations

1. **Prefix the text with a task hint.** nomic-embed-text supports task-specific prefixes. For lessons, use `search_document: <lesson text>`. For queries, use `search_query: <prompt text>`. This activates different encoding paths and significantly improves retrieval quality. This is documented in the Nomic model card and should be implemented from day one.

2. **Hybrid search: keyword + semantic.** ChromaDB does not natively support BM25/keyword search, but we can add a lightweight keyword index alongside. When the embedding similarity is low, fall back to keyword matching. Implementation: store key terms in metadata and use `$contains` filters.

3. **Threshold tuning.** Start with `min_score: 0.55` and adjust based on observed quality. Too low = noisy results that waste context tokens. Too high = missed relevant lessons. Log all query-result pairs for offline analysis.

4. **Model upgrade path.** If quality is insufficient after ~500 lessons, upgrade to mxbai-embed-large. The re-embedding batch job is automated and takes ~30 seconds for 1K lessons. The architecture abstracts the model choice behind the Ollama API, so switching is a config change + re-embed.

5. **Rich lesson text.** Encourage lesson authors (yourself) to write descriptive lessons that include the problem, the context, and the solution. A lesson that says "use flag X" is less retrievable than "When deploying to production and the Docker container fails to start due to missing environment variables, use the --env-file flag to pass the .env file."

### Empirical Validation Plan

After ingesting the first 15 lessons, run 20 representative queries manually and measure:
- **Precision@3**: Of the top 3 returned lessons, how many are actually relevant?
- **Recall@5**: Of the lessons that should have been returned, how many were in the top 5?

Target: Precision@3 > 0.7 and Recall@5 > 0.8. If these are not met, escalate to mxbai-embed-large.

---

## Risk 4: Category Classification Accuracy

**Severity: LOW | Probability: MEDIUM (40%)**

### The Risk

Automatic category classification (when users do not supply categories) may misclassify lessons, leading to:
- Wrong categories pollute the category hierarchy.
- Category-filtered queries miss relevant lessons.
- Category centroids drift as misclassified lessons shift the centroid embeddings.

### The Nuance

This risk is lower severity than it appears because **category filtering is optional and rarely used in the hot path.** The UserPromptSubmit hook queries across all categories by default (no `where` clause). Categories are primarily useful for:
- Manual browsing/exploration of the lesson database.
- Future features like "show me all lessons about CI/CD."
- Organizational hygiene.

If a lesson is miscategorized, it is still findable by semantic search across the full collection.

### Mitigations

1. **Default to manual categories.** The ingestion CLI should prompt for categories (with autocomplete from the existing taxonomy). Auto-classification is the fallback, not the primary path.

2. **Conservative auto-classification.** When confidence is low, assign the broadest parent category (e.g., `development/` instead of `development/frontend/styling`). Overly specific wrong categories are worse than overly broad correct ones.

3. **Editable categories.** The `PUT /api/lessons/{id}` endpoint allows correcting categories after the fact. Build a simple CLI command: `lesson-search recategorize <id> <new-categories>`.

4. **No cascading effects.** Categories are stored as flat strings in metadata, not in a relational structure. Changing a lesson's categories does not affect other lessons or the taxonomy tree.

### Category Classification Quality Target

At 15 lessons with keyword-based classification, expect ~80% accuracy (12/15 correctly categorized). At 500+ lessons with centroid-based classification, expect ~85% accuracy. These are acceptable for a personal tool where occasional manual correction is easy.

---

## Risk 5: Scaling Concerns at 10K+ Lessons

**Severity: LOW | Probability: LOW (15%)**

### The Risk

The system is designed for 100s to low thousands of lessons. What happens at 10K+?

| Scale | ChromaDB Query Time | Memory Usage (HNSW) | Ollama Latency | Total |
|-------|--------------------|--------------------|----------------|-------|
| 100 | <1ms | ~5MB | ~20ms | ~25ms |
| 1,000 | ~2ms | ~30MB | ~20ms | ~27ms |
| 10,000 | ~5ms | ~300MB | ~20ms | ~30ms |
| 100,000 | ~10-15ms | ~3GB | ~20ms | ~40ms |
| 1,000,000 | ~20-30ms | ~30GB | ~20ms | ~55ms |

At 10K lessons, the system stays well within budget. At 100K, it is borderline. At 1M, it exceeds the budget and requires architectural changes.

### Reality Check

10K+ personal lessons is extremely unlikely. At 5 lessons per day (a high rate), it takes 5.5 years to reach 10K. The more realistic concern is **organizational deployment**: if this system is shared across a team, the combined lesson count could grow faster.

### Mitigations for Scale

1. **Incremental HNSW parameters.** ChromaDB allows tuning `hnsw:M` (graph connectivity) and `hnsw:ef` (search beam width). At >10K, reduce `hnsw:M` from 32 to 16 to halve memory usage with modest quality loss.

2. **Collection sharding by top-level category.** Split the single `lessons` collection into multiple: `lessons_development`, `lessons_devops`, `lessons_workflow`. Query the relevant collection(s) based on a quick category classifier on the prompt. This keeps each collection small.

3. **Archival.** Old lessons (>1 year, low access count) can be moved to an archive collection that is only searched when the primary collection yields low-score results.

4. **Switch to LanceDB.** If memory becomes a constraint (>3GB for the HNSW index), LanceDB's disk-based approach with IVF-PQ indexing handles 1M+ vectors in <100MB memory. This is the escape hatch for true scale, requiring a data migration but no API changes.

5. **Embedding dimension reduction.** nomic-embed-text v1.5 supports Matryoshka representations. Truncate from 768 to 256 dimensions to reduce memory by ~67% with ~5-10% quality loss. This is a config change, not an architectural change.

---

## Risk 6: Hook Script Reliability

**Severity: LOW | Probability: LOW (10%)**

### The Risk

The UserPromptSubmit hook runs on every single user prompt. If it fails noisily, hangs, or produces malformed output, it could:
- Inject garbage context that confuses Claude.
- Block prompt processing (exit code 2).
- Slow down every interaction.

### Mitigations

1. **Defense in depth in the hook script:**
   - `set -euo pipefail` catches all errors.
   - `curl --max-time 2` hard-caps the HTTP call.
   - All JSON parsing wrapped in `|| exit 0` fallbacks.
   - Never exit with code 2 (which would block the prompt).

2. **Hook timeout of 5 seconds** in the Claude Code settings. Even if curl hangs, the hook is killed after 5 seconds and Claude proceeds.

3. **No complex logic in the hook.** The hook is a thin HTTP client. All logic (embedding, search, formatting) lives in the server. The hook's job is: read stdin, extract prompt, POST to server, print result.

4. **Testing harness.** Create a test script that exercises the hook with various inputs:
   ```bash
   echo '{"prompt": "How do I fix CI?"}' | ~/.local/bin/lesson-search-hook
   echo '{"prompt": ""}' | ~/.local/bin/lesson-search-hook
   echo '{}' | ~/.local/bin/lesson-search-hook
   echo 'garbage' | ~/.local/bin/lesson-search-hook
   ```
   All four should exit 0 with either formatted output or nothing.

---

## Risk 7: Server Process Consumes Resources When Idle

**Severity: LOW | Probability: LOW (10%)**

### The Risk

The FastAPI server runs continuously via launchd, consuming memory even when Claude Code is not in use. The baseline footprint:
- FastAPI + uvicorn: ~60-80MB
- ChromaDB HNSW index (1K lessons, 768d): ~30MB
- Python runtime: ~30MB
- **Total: ~120-140MB idle**

On a machine with 16-64GB RAM, this is negligible. On a constrained system, it adds up alongside Ollama (~0.5GB for nomic-embed-text).

### Mitigations

1. **Acceptable cost.** 140MB for a persistent local service is well within reason for a development machine. Ollama itself uses 500MB+ and is already accepted.

2. **On-demand startup (alternative).** If resources are tight, replace launchd KeepAlive with a socket-activated approach: the hook script starts the server on first use, and the server shuts itself down after 10 minutes of inactivity. This adds ~1-2 seconds latency on the first prompt after idle but saves memory otherwise. Implementation complexity is moderate.

3. **Memory-mapped HNSW.** ChromaDB memory-maps the HNSW index, meaning the OS can page it out under memory pressure. The 30MB HNSW allocation is virtual, not necessarily physical, when the system is under pressure.

---

## Risk Summary Matrix

| # | Risk | Severity | Probability | Mitigation Confidence |
|---|------|----------|-------------|----------------------|
| 1 | Latency exceeds 50ms | HIGH | MEDIUM (30%) | HIGH -- Ollama keep-alive + warm ping covers the main case |
| 2 | Ollama not running | MEDIUM | MEDIUM (25%) | HIGH -- Silent failure is bulletproof |
| 3 | Embedding quality for code | MEDIUM | MEDIUM (35%) | MEDIUM -- Requires empirical validation; upgrade path exists |
| 4 | Category classification accuracy | LOW | MEDIUM (40%) | HIGH -- Categories are optional in the hot path |
| 5 | Scaling at 10K+ lessons | LOW | LOW (15%) | HIGH -- Multiple escape hatches, unlikely to be needed |
| 6 | Hook script reliability | LOW | LOW (10%) | HIGH -- Defensive coding, tested failure modes |
| 7 | Idle resource consumption | LOW | LOW (10%) | HIGH -- 140MB is acceptable; on-demand alternative exists |

### Overall Assessment

The architecture has **no blocking risks**. The highest-severity risk (latency) has strong mitigations. The most likely risk (embedding quality for technical content) has a clear validation plan and upgrade path. The system is designed with **silent failure as a core principle**: when anything goes wrong, Claude Code works exactly as it does today, without lesson context. This means the downside of any failure is "no improvement" rather than "degraded experience."
