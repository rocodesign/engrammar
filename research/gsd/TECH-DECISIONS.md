# Semantic Lesson Search System -- Technology Decisions

## Decision 1: Vector Database

### Recommendation: **ChromaDB** (in-process, persistent)

**Confidence: HIGH (90%)**

#### Candidates Evaluated

| Database | Architecture | Query Latency (1K vectors) | Memory Usage | ANN Index | Python API |
|----------|-------------|---------------------------|--------------|-----------|------------|
| **ChromaDB** | In-process, HNSW in-memory | ~2-5ms | ~50-100MB for 10K/768d vectors | HNSW (hnswlib, C++) | First-class, Pythonic |
| **LanceDB** | In-process, disk-based Lance format | ~5-10ms (brute force at this scale) | Very low (~10-20MB) | IVF-PQ (optional, for >100K) | Good, Rust bindings |
| **sqlite-vec** | SQLite extension, brute-force | ~50-200ms for 768d at 10K | Low | None (brute-force only) | Via sqlite3 module |

#### Why ChromaDB

1. **Lowest query latency for our scale.** HNSW in-memory index delivers 2-5ms query times for collections under 10K vectors. The index is built once on startup and stays in RAM. At our target scale (100s to low thousands of lessons), this is effectively instant.

2. **Mature Python-first API.** ChromaDB is designed for exactly this use case: embed-and-retrieve with metadata filtering. The API is minimal and Pythonic:
   ```python
   collection.query(query_embeddings=[vec], n_results=5, where={"category_l1": {"$contains": "devops"}})
   ```

3. **Persistent storage with fast startup.** ChromaDB persists the HNSW index and all documents to disk in SQLite + binary files. On server restart, the index is memory-mapped, providing fast cold-start (~200-500ms for 10K vectors).

4. **Built-in metadata filtering.** ChromaDB supports `where` clauses on metadata fields, which is essential for hierarchical category filtering. LanceDB has this too, but sqlite-vec would require manual implementation.

5. **Active development.** ChromaDB's 2025 Rust-core rewrite delivers up to 4x performance improvements. As of February 2026, it remains one of the top embedded vector databases.

#### Why Not LanceDB

LanceDB is excellent and was a close second. The disk-based Lance format shines at scale (millions of vectors) with minimal memory, but at our target scale (<10K vectors), ChromaDB's in-memory HNSW is faster. LanceDB's brute-force scan at small scale is ~5-10ms vs ChromaDB's ~2-5ms. The difference is small but ChromaDB's API is more battle-tested for this exact use case.

LanceDB would be the better choice if we expected to scale beyond 100K lessons, which seems unlikely for personal lessons but could matter for skill discovery at organizational scale.

#### Why Not sqlite-vec

sqlite-vec is appealing for its simplicity (just a SQLite extension) and zero-dependency deployment. However, it performs brute-force scans with no ANN indexing. At 10K vectors with 768 dimensions, query times reach 50-200ms, which threatens our 50ms total latency budget. The newer sqlite-vector fork is faster but still lacks ANN. sqlite-vec is a reasonable fallback if ChromaDB's dependency footprint becomes a problem.

## Decision 2: Embedding Model

### Recommendation: **nomic-embed-text v1.5** via Ollama

**Confidence: HIGH (85%)**

#### Candidates Evaluated

| Model | Dimensions | MTEB Retrieval Score | Memory | Speed (Apple Silicon) | Context Length |
|-------|-----------|---------------------|--------|----------------------|----------------|
| **nomic-embed-text v1.5** | 768 | ~55 (v1 baseline; v1.5 improved Matryoshka support) | 0.5GB | ~9,340 tok/s (M2 Max) | 8,192 tokens |
| **mxbai-embed-large** | 1024 | ~64.7 | 1.2GB | ~6,780 tok/s (M2 Max) | 512 tokens |
| **all-minilm** | 384 | ~42 | 0.2GB | ~15,000+ tok/s | 256 tokens |
| **nomic-embed-text-v2-moe** | 768 | improved over v1 | ~1.0GB (475M params, 305M active) | slower due to MoE | 8,192 tokens |

#### Why nomic-embed-text v1.5

1. **Best latency-to-quality ratio.** At 0.5GB memory and 768 dimensions, it delivers good retrieval quality with very fast inference. Single embedding requests complete in ~15-25ms on Apple Silicon, which is critical for our <50ms budget.

2. **Long context window (8,192 tokens).** Lessons can be paragraphs or even multi-paragraph entries. The 8K context window handles this without truncation. all-minilm's 256-token limit would force aggressive truncation.

3. **Matryoshka embedding support (v1.5).** If storage becomes a concern, we can truncate embeddings to 256 or 512 dimensions with graceful quality degradation. This is future-proofing at no cost.

4. **Surpasses OpenAI text-embedding-ada-002** on both short and long context tasks, while running entirely locally. This validates that local embeddings can match cloud quality for this use case.

5. **Ollama-native.** Ships as a first-class Ollama model (`ollama pull nomic-embed-text`). No conversion or GGUF wrangling required.

#### Why Not mxbai-embed-large

mxbai-embed-large has significantly better MTEB scores (~64.7 vs ~55), but the tradeoffs are:
- **2.4x more memory** (1.2GB vs 0.5GB)
- **~38% slower** inference on Apple Silicon
- **512-token context limit** vs 8,192 -- this is the dealbreaker. Many lessons exceed 512 tokens.
- **1024 dimensions** increases storage and slightly increases ChromaDB query time.

If lessons were very short (tweet-length) and quality was paramount, mxbai-embed-large would be the better choice.

#### Why Not all-minilm

all-minilm is the fastest option (~15K+ tok/s) with the smallest memory footprint (0.2GB), but:
- **256-token context limit** is far too restrictive for lesson text.
- **384 dimensions** produce less semantically rich embeddings.
- **MTEB score of ~42** means significantly worse retrieval quality. At 10K+ lessons, the difference between finding the right lesson and surfacing irrelevant ones becomes critical.

#### Why Not nomic-embed-text-v2-moe

The v2 MoE model is newer and shows improved multilingual performance, but:
- **Larger model** (~1.0GB, 475M params) with slower inference due to MoE routing.
- **Diminishing returns for English-only technical content.** The MoE architecture's strengths are in multilingual generalization, which is not needed here.
- **Less battle-tested** on Ollama as of February 2026.

### Embedding Model Upgrade Path

Start with nomic-embed-text v1.5. If retrieval quality is unsatisfactory after reaching ~500 lessons, upgrade to mxbai-embed-large and re-embed all lessons (a one-time batch job taking ~30 seconds for 1K lessons). The server's `/api/health` endpoint reports the current model, and the re-embedding can be triggered via a CLI command.

## Decision 3: Server Framework

### Recommendation: **FastAPI** with uvicorn

**Confidence: HIGH (95%)**

#### Candidates Evaluated

| Framework | Throughput | Latency | Async Support | Startup Time | Memory |
|-----------|-----------|---------|---------------|-------------|--------|
| **FastAPI + uvicorn** | ~2,800-15,000 req/s | ~45ms p50 | Native (ASGI) | ~1-2s | ~127MB |
| **Flask + gunicorn** | ~900-3,000 req/s | ~142ms p50 | Bolt-on | ~1-2s | ~156MB |
| **Raw HTTP (http.server)** | ~500 req/s | ~200ms+ | None | ~0.5s | ~50MB |
| **Starlette** (FastAPI without extras) | ~3,000-18,000 req/s | ~40ms p50 | Native (ASGI) | ~1s | ~100MB |

#### Why FastAPI

1. **Async-native.** The Ollama HTTP call and ChromaDB query can potentially be parallelized. More importantly, the ASGI server does not block on I/O, meaning if two Claude Code sessions hit the server simultaneously, they are handled concurrently.

2. **Automatic request/response validation.** Pydantic models for the API contract catch malformed requests at the framework level. This is significant for a long-running daemon where silent data corruption would be hard to debug.

3. **Built-in `/docs` endpoint.** Swagger UI auto-generated from the Pydantic models. Useful for development and debugging.

4. **Lower latency than Flask.** FastAPI achieves ~45ms p50 latency vs Flask's ~142ms. For a system targeting <50ms total, every millisecond of framework overhead matters.

5. **De facto standard for Python APIs in 2025-2026.** Largest ecosystem, most examples, best maintained.

#### Why Not Raw HTTP or Starlette

Raw `http.server` would minimize dependencies but lacks routing, validation, and async support. Starlette (which FastAPI is built on) would save ~20MB memory by skipping Pydantic, but the validation and auto-docs are worth the overhead for a long-running daemon.

### Server Implementation Sketch

```python
# server.py
from fastapi import FastAPI
from pydantic import BaseModel
import chromadb
import httpx

app = FastAPI(title="Lesson Search", version="0.1.0")
chroma_client = chromadb.PersistentClient(path="~/.local/share/lesson-search/db")
collection = chroma_client.get_or_create_collection("lessons", metadata={"hnsw:space": "cosine"})
ollama_client = httpx.AsyncClient(base_url="http://127.0.0.1:11434", timeout=5.0)

class QueryRequest(BaseModel):
    prompt: str
    top_k: int = 5
    categories: list[str] | None = None
    min_score: float = 0.4

@app.post("/api/query")
async def query_lessons(req: QueryRequest):
    # 1. Embed prompt
    embed_resp = await ollama_client.post("/api/embed", json={
        "model": "nomic-embed-text",
        "input": req.prompt
    })
    embedding = embed_resp.json()["embeddings"][0]

    # 2. Build ChromaDB where clause
    where = None
    if req.categories:
        where = {"$or": [{"category_l1": {"$contains": c}} for c in req.categories]}

    # 3. Query
    results = collection.query(
        query_embeddings=[embedding],
        n_results=req.top_k,
        where=where,
        include=["documents", "metadatas", "distances"]
    )

    # 4. Format and filter by min_score
    lessons = []
    for i, doc in enumerate(results["documents"][0]):
        score = 1 - results["distances"][0][i]  # cosine distance -> similarity
        if score >= req.min_score:
            lessons.append({
                "id": results["ids"][0][i],
                "text": doc,
                "score": round(score, 3),
                "categories": results["metadatas"][0][i].get("categories", "").split(",")
            })

    return {"lessons": lessons}
```

## Decision 4: Server Lifecycle Management

### Recommendation: **macOS launchd LaunchAgent** with health-check wrapper

**Confidence: HIGH (90%)**

#### Options Evaluated

| Approach | Auto-start on login | Auto-restart on crash | Resource usage when idle | Complexity |
|----------|--------------------|-----------------------|--------------------------|------------|
| **launchd LaunchAgent** | Yes | Yes (KeepAlive) | Minimal (process stays warm) | Medium |
| **Manual start** | No | No | Zero when not running | Low |
| **Docker container** | Via Docker Desktop | Yes (restart policy) | ~200MB+ Docker overhead | High |
| **Homebrew service** | Yes (via launchd) | Yes | Same as launchd | Medium |

#### Why launchd

1. **Native macOS process management.** No additional dependencies. launchd is the init system on macOS, and LaunchAgents are the standard way to run user-level daemons.

2. **KeepAlive with crash recovery.** If the server crashes, launchd restarts it automatically. With `SuccessfulExit: false`, clean shutdowns (exit 0) do not trigger restart, but crashes (non-zero exit) do.

3. **Zero overhead when running.** Unlike Docker, there is no container runtime. The FastAPI process runs directly, using ~60-130MB when idle (ChromaDB index in memory).

4. **Login-triggered startup.** The LaunchAgent loads when the user logs in. No need to remember to start the server.

### LaunchAgent Configuration

**File: `~/Library/LaunchAgents/com.user.lesson-search.plist`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.lesson-search</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/user/.local/share/lesson-search/venv/bin/uvicorn</string>
        <string>lesson_search.server:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>7731</string>
        <string>--log-level</string>
        <string>warning</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/user/.local/share/lesson-search</string>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/user/.local/share/lesson-search/logs/stdout.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/user/.local/share/lesson-search/logs/stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
```

**Management commands:**

```bash
# Load (enable and start)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.lesson-search.plist

# Unload (stop and disable)
launchctl bootout gui/$(id -u)/com.user.lesson-search

# Check status
launchctl print gui/$(id -u)/com.user.lesson-search

# Force restart
launchctl kickstart -k gui/$(id -u)/com.user.lesson-search
```

### Ollama Lifecycle

Ollama installs its own LaunchAgent (`com.ollama.ollama`) when installed via the macOS app. It stays resident and loads models on first request. If Ollama is not running when the lesson search server tries to embed, the server should:

1. Attempt the Ollama call.
2. On connection refused, return an empty result set (graceful degradation).
3. Log a warning to stderr.
4. The hook script treats this as "no lessons found" and exits silently.

## Decision 5: Storage Format and Location

### Recommendation: XDG-style local directory

**Confidence: HIGH (95%)**

#### Directory Layout

```
~/.local/share/lesson-search/
  db/                          # ChromaDB persistent storage
    chroma.sqlite3             # Metadata + document store
    *.bin                      # HNSW index files
  logs/
    stdout.log
    stderr.log
  config.yaml                  # Server configuration
  venv/                        # Python virtual environment
    bin/uvicorn
    lib/python3.12/...
```

#### config.yaml

```yaml
server:
  host: 127.0.0.1
  port: 7731

ollama:
  base_url: http://127.0.0.1:11434
  model: nomic-embed-text
  timeout_seconds: 5

chromadb:
  path: ~/.local/share/lesson-search/db
  collection: lessons
  hnsw_space: cosine

query:
  default_top_k: 5
  default_min_score: 0.4

categories:
  taxonomy_file: ~/.local/share/lesson-search/taxonomy.yaml
  auto_classify: true
```

#### Why This Layout

- **`~/.local/share/`** follows the XDG Base Directory spec for user data, avoiding cluttering `$HOME`.
- **Self-contained venv** means the server's Python dependencies do not conflict with system Python or other projects.
- **Separate logs directory** for easy debugging. Logs are rotated by size (configured in uvicorn).
- **Config file outside the venv** so updates to the server code do not overwrite user configuration.

#### Backup

The entire `~/.local/share/lesson-search/` directory can be backed up or synced. The ChromaDB SQLite file is the source of truth; the HNSW binary index is rebuilt from it on startup if missing.
