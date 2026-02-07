# Semantic Lesson Search: Architecture Alternatives Analysis

## Current Setup (Baseline)

The existing system uses a flat markdown file (`~/.shared-cli-agents/lessons-learned.md`,
~22 lines, ~15 lessons) loaded via `SessionStart` hook. A Python script
(`extract-lessons.py`) runs Claude Haiku headless to extract lessons from session
facets, merges them with word-overlap dedup, and regenerates the markdown. Every
session reads the entire file into context.

**What works today**: Simple, zero infrastructure, always available.
**What breaks at scale**: At 1000+ lessons, injecting all of them wastes context
tokens and dilutes relevance. The word-overlap similarity check (`_similar()`) is
crude and will produce duplicates as vocabulary grows.

---

## Challenge 1: Do We Need Ollama?

### The assumed approach
Run Ollama locally with `nomic-embed-text` or `mxbai-embed-large`. Ollama stays
resident in memory, serves embeddings via HTTP on localhost. ~20-30ms per query on
Apple Silicon.

### Alternative A: FastEmbed (ONNX Runtime, no Ollama)

[FastEmbed](https://github.com/qdrant/fastembed) is a lightweight Python library
from Qdrant that runs embedding models via ONNX Runtime. No GPU required, no daemon
process, no Docker, no Ollama.

**Advantages**:
- Starts in <1 second (just loads an ONNX file)
- No background process to manage
- ~40% faster inference than PyTorch on CPU
- Tiny dependency footprint (no torch, no cuda)
- Can be invoked directly from the hook script

**Disadvantages**:
- Model loads on every invocation unless wrapped in a persistent process
- Smaller model selection than Ollama

**Verdict**: FastEmbed is the better choice for this use case. We are embedding
*one query* per user message (not batching thousands). Loading a quantized ONNX
model from disk takes <500ms on Apple Silicon with warm filesystem cache. Combined
with the vector search, total latency stays under 50ms after the first call. If cold
start matters, wrap it in a Unix socket server (see Challenge 3).

### Alternative B: Anthropic's Voyage AI Embeddings (Cloud API)

Anthropic recommends [Voyage AI](https://docs.voyageai.com/docs/pricing) for
embeddings. First 200M tokens free. Voyage-3 and Voyage-3-large are
state-of-the-art.

**Advantages**:
- Zero local compute
- Higher quality embeddings than local models (especially for nuanced lessons)
- No model to download or manage

**Disadvantages**:
- Network latency: 50-200ms per call (kills the <50ms target)
- Requires internet connectivity (breaks offline workflow)
- Privacy: sends every user prompt to an external API
- Cost at scale: each user message = 1 API call

**Verdict**: Reject for the primary path. Could be used as a one-time batch job to
pre-embed all lessons with high quality, then use a simpler local model for query
embedding. The embedding spaces would need to be compatible (they are not), so this
is a dead end unless you use the same model for both.

### Alternative C: Apple CoreML / MLX

Convert an embedding model to CoreML format using `coremltools`, or use Apple's
[MLX framework](https://github.com/ml-explore/mlx) which runs natively on Apple
Silicon's unified memory.

**Advantages**:
- Native Metal acceleration, zero-copy memory
- MLX has first-class sentence-transformer support
- No external runtime (Ollama, ONNX)
- Potentially the fastest option on macOS

**Disadvantages**:
- macOS-only (breaks if user switches to Linux)
- MLX ecosystem is newer, fewer models validated
- CoreML conversion can be brittle for transformer architectures

**Verdict**: Interesting for a future optimization but premature. MLX is the more
promising path (pure Python, numpy-like API, M-series optimized). However, FastEmbed
with ONNX is more portable and already proven. Revisit MLX when/if ONNX latency
becomes a bottleneck.

### Alternative D: llama.cpp Embedding Server

Run `llama-server --embedding` with a GGUF-quantized embedding model. Same C++
performance as Ollama (Ollama uses llama.cpp under the hood) but without Ollama's
overhead.

**Advantages**:
- Same performance as Ollama, lighter wrapper
- OpenAI-compatible API out of the box
- Can run as a launchd service on macOS

**Disadvantages**:
- Still requires a persistent server process
- Managing GGUF models manually vs Ollama's `pull` convenience
- Marginal improvement over Ollama for this use case

**Verdict**: If we go the persistent server route, llama.cpp is leaner than Ollama.
But the whole point of this challenge is questioning whether we need a server at all.

### Recommendation: FastEmbed for V1, Ollama optional for V2

Start with FastEmbed. It eliminates the "is Ollama running?" failure mode entirely.
The model loads from a cached ONNX file in the hook process. If latency proves too
high (>50ms), wrap FastEmbed in a persistent Unix socket server or migrate to Ollama.

---

## Challenge 2: Do We Need a Vector Database?

### The assumed approach
Run a vector DB (Qdrant, ChromaDB, Milvus) that stays resident and serves queries.

### The scale reality check

At 1,000 lessons with 384-dimensional embeddings:
- Raw data: 1,000 x 384 x 4 bytes = **1.5 MB**
- With metadata: ~3 MB total

At 10,000 lessons: **15 MB**

This is not a vector database problem. This is a numpy array problem.

### Alternative A: numpy + cosine similarity (brute force)

```python
import numpy as np

# Load pre-computed embeddings (memory-mapped for instant load)
embeddings = np.load("lessons.npy", mmap_mode="r")  # zero-copy
query_vec = embed("user prompt")
scores = embeddings @ query_vec  # dot product (normalized = cosine sim)
top_k = np.argpartition(scores, -5)[-5:]
```

**Performance at 1,000 vectors**: <0.1ms (microseconds)
**Performance at 10,000 vectors**: <1ms
**Performance at 100,000 vectors**: ~5ms

**Advantages**:
- Zero dependencies beyond numpy
- Memory-mapped file = instant "load", no startup cost
- Trivially debuggable
- No server process, no port, no connection management

**Disadvantages**:
- No built-in metadata filtering (but easily added with a mask array)
- No HNSW indexing (unnecessary below 100K vectors)
- Manual management of add/delete operations

**Verdict**: This is the right answer for V1. The math is unambiguous: brute-force
cosine similarity on 1,000-10,000 vectors is faster than the overhead of connecting
to a database.

### Alternative B: USearch (single-file HNSW)

[USearch](https://github.com/unum-cloud/USearch) is a single-header-file vector
search engine with Python bindings. Memory-mapped, HNSW-based, claims 10x faster
than FAISS.

**Advantages**:
- Memory-mapped index file (zero load time)
- HNSW gives O(log n) search, future-proof to millions
- Single file, no server, pip install
- Supports custom distance metrics

**Disadvantages**:
- Overkill below 50K vectors (brute force is faster due to no graph traversal)
- One more dependency to maintain

**Verdict**: Excellent upgrade path from numpy when lessons exceed ~50K. Keep it in
the architecture as "Phase 2 indexing backend" but do not introduce it on day one.

### Alternative C: sqlite-vec

[sqlite-vec](https://github.com/asg017/sqlite-vec) is a SQLite extension for vector
search. Pure C, no dependencies, runs anywhere SQLite runs.

**Advantages**:
- SQLite is already everywhere; familiar tooling
- Can store lessons + embeddings + metadata in one file
- SQL for metadata filtering (categories, dates, tags)
- Atomic transactions for add/update/delete

**Disadvantages**:
- Slower than raw numpy for pure vector search
- Extension installation can be fiddly on macOS
- Less mature than the numpy/FAISS ecosystem

**Verdict**: Strong contender for the "storage layer" even if not the primary search
path. Consider: store lessons in SQLite (structured data, categories, history), but
keep a numpy memory-mapped array as the search index. Best of both worlds.

### Alternative D: Hybrid BM25 + Vector

For small corpora, keyword matching (BM25) can outperform vector search on exact
terms. A hybrid approach:

1. BM25 over lesson text (catches exact tool names, error messages, paths)
2. Vector similarity over embeddings (catches semantic matches)
3. Reciprocal Rank Fusion to merge results

**Advantages**:
- Catches "picasso component" even if the embedding model has weak tool-name coverage
- BM25 is essentially free (rank_bm25 library, <1ms on small corpus)
- Handles the long tail of specific technical terms better

**Disadvantages**:
- Two retrieval paths to maintain
- Score normalization requires tuning

**Verdict**: Add BM25 as a secondary signal in V1. It is nearly free to implement
and meaningfully improves retrieval quality for technical content where exact tool
names, file paths, and error strings matter.

### Recommendation: numpy + BM25 hybrid, SQLite for storage

The architecture becomes:
```
lessons.db (SQLite)         -- source of truth: text, category, metadata
lessons.npy (memory-mapped) -- precomputed embeddings for vector search
BM25 index (in-memory)      -- rebuilt on startup from SQLite
```

Total infrastructure: zero servers, two files, one pip install.

---

## Challenge 3: Do We Need a Persistent Server?

### The assumed approach
A FastAPI/Flask server running on localhost, keeps model + index in memory, responds
to HTTP queries.

### Alternative A: Direct in-process execution from the hook

The `UserPromptSubmit` hook runs a command. That command can be a Python script that:
1. Loads a memory-mapped numpy array (instant, no copy)
2. Loads a quantized ONNX model via FastEmbed (~200-500ms cold, ~0ms warm via OS cache)
3. Embeds the query (~10-20ms)
4. Computes cosine similarity (~0.1ms)
5. Returns top-k lessons as JSON

**Total latency**: ~30ms warm, ~500ms cold (first message of session)

**Advantages**:
- No server to start, monitor, restart, or debug
- No port conflicts, no "is it running?" checks
- Process isolation: crash in search does not affect Claude Code
- Works identically on macOS and Linux

**Disadvantages**:
- Cold start on first message (~500ms, barely noticeable)
- Python interpreter startup (~50ms) adds to every call
- No connection pooling or model caching across calls

**Verdict**: This is the simplest architecture that could work. The cold start is
acceptable because (a) the first message of a session is typically slow anyway
(loading context, reading AGENTS.md), and (b) subsequent calls benefit from OS-level
filesystem caching of the ONNX model and numpy files.

### Alternative B: Unix domain socket server

A Python process listens on `/tmp/lesson-search.sock`. The hook script connects via
Unix socket, sends the query, gets results.

**Advantages**:
- Eliminates cold start entirely
- Model stays loaded in memory
- Unix socket is faster than HTTP (no TCP overhead)
- Can be managed via launchd on macOS

**Disadvantages**:
- Another process to manage (start on login, restart on crash)
- Debugging is harder (logs, socket file cleanup)
- Adds complexity for marginal latency gain

**Verdict**: Good upgrade path if cold start becomes annoying, but not needed for V1.

### Alternative C: MCP Server (Claude Code native)

Build the lesson search as an MCP server. Claude Code connects to it directly and
can call `search_lessons` as a tool.

```json
{
  "mcpServers": {
    "lesson-search": {
      "command": "python3",
      "args": ["~/.claude/mcp-servers/lesson-search/server.py"],
      "env": {}
    }
  }
}
```

**Advantages**:
- Native Claude Code integration (shows up in tool list)
- Claude decides when to search, not a blanket hook on every message
- Can expose multiple tools: `search_lessons`, `add_lesson`, `list_categories`
- MCP servers stay running for the session (no cold start after first call)
- Could use MCP Tool Search for lazy loading (95% context reduction)
- Aligns with the skill discovery reuse goal (same MCP server, more tools)

**Disadvantages**:
- Claude must decide to call the tool (may skip it)
- Adds tool descriptions to context (unless using Tool Search plugin)
- More complex than a simple hook script
- MCP servers can be flaky (stdio transport, process lifecycle)

**Verdict**: THIS IS THE WINNER for V2. The MCP approach has a critical advantage:
it makes the lesson search *composable*. The same server can serve lessons, skills,
documentation, and anything else that benefits from semantic search. Claude can call
it selectively rather than injecting context on every single message.

However, for V1, the hook approach is simpler and guarantees lessons are always
injected. The MCP approach requires Claude to recognize it should search, which it
may not always do.

### Alternative D: Hybrid Hook + MCP

**Best of both worlds**:
1. `UserPromptSubmit` hook does a fast, lightweight search (top-3 lessons) and
   injects them as `additionalContext`. This ensures minimum-viable context on every
   message.
2. MCP server provides `search_lessons` tool for when Claude wants deeper/targeted
   search. Also provides `add_lesson`, `edit_lesson`, `list_categories` for
   management.

The hook is the safety net. The MCP server is the power tool.

### Recommendation: Hook-first (V1), Hook + MCP (V2)

**V1**: Python script invoked by `UserPromptSubmit` hook. Loads memory-mapped numpy
embeddings, embeds query via FastEmbed, returns top-3 as `additionalContext`.

**V2**: Add MCP server alongside the hook. Same search backend, but Claude can also
explicitly search, manage lessons, and the same server serves skill discovery.

---

## Challenge 4: What About Using Claude's Own Understanding?

### The idea
Skip embeddings entirely. Send the user's prompt + a list of lesson categories to a
fast Claude model. Let Claude pick which categories are relevant. Then inject the
lessons from those categories.

### Analysis

With ~15 categories and a fast model (Haiku), this could work:

```
Prompt: "Fix the inline style ESLint error in the sidebar"
Claude picks: ["styling", "code-patterns"]
-> Inject lessons from those categories
```

**Advantages**:
- No embedding model, no vector search, no numpy
- Claude understands context better than any embedding model
- Category selection is a classification task, which LLMs excel at
- Could use the existing `claude -p` headless pattern

**Disadvantages**:
- Latency: even Haiku takes 200-500ms per call (network + inference)
- Cost: every user message triggers an API call
- Fragility: depends on Anthropic API availability
- Accuracy ceiling: with 1000+ lessons per category, still need within-category ranking

**Verdict**: Smart for category routing, not for lesson selection. This approach
shines as a pre-filter: use Claude to identify 2-3 relevant categories, then use
vector search within those categories. But adding an API call to every message is too
slow and too fragile for V1. Revisit when/if categories become very deep (100+
lessons per category).

A lighter version: use the hierarchical category system as a simple keyword filter.
If the user's message contains "storybook" or "story", filter to
`development/frontend/storybook` before vector search. Zero latency, zero cost,
surprisingly effective.

---

## Challenge 5: Could This Be an MCP Server That Claude Calls Directly?

Already addressed in Challenge 3 (Alternative C). Yes, and it should be -- but as
V2, not V1.

The MCP approach becomes particularly powerful when combined with:
- **Tool Search plugin**: Claude only sees the `search_lessons` tool when it is
  actually relevant, keeping context clean
- **Skill discovery**: Same MCP server exposes `search_skills`, creating a unified
  knowledge layer
- **Management tools**: `add_lesson`, `remove_lesson`, `reclassify_lesson` as MCP
  tools, giving Claude the ability to maintain the knowledge base

---

## Final Architecture Recommendation

### V1: Minimal, Hook-Based (ship in a weekend)

```
UserPromptSubmit hook
    |
    v
search-lessons.py
    |-- FastEmbed (ONNX, ~10ms to embed query)
    |-- numpy mmap (lessons.npy, <0.1ms search)
    |-- rank_bm25 (keyword fallback, <1ms)
    |-- SQLite (lessons.db: text, categories, metadata)
    |
    v
stdout -> additionalContext (top 3 lessons)
```

**Dependencies**: fastembed, numpy, rank_bm25, sqlite3 (stdlib)
**Infrastructure**: zero servers, two files
**Latency**: ~30ms warm, ~500ms cold (first message)
**Failure mode**: if script crashes, Claude Code continues without lessons (graceful)

### V2: MCP Server + Hook (ship in a month)

```
UserPromptSubmit hook (top-3 lessons, always)
    +
MCP Server: lesson-search
    |-- search_lessons(query, categories?, limit?)
    |-- search_skills(query)  <-- reuse for skill discovery
    |-- add_lesson(text, category?)
    |-- remove_lesson(id)
    |-- list_categories()
    |-- get_lesson_stats()
```

### V3: Intelligent Routing Layer (future)

The MCP server evolves into a unified knowledge router:
- Lessons (what to avoid / what works)
- Skills (what tools are available)
- Documentation (how things work)
- Project conventions (how this codebase does things)

Every user message gets routed to the right knowledge, whether that is a lesson, a
skill invocation, or a documentation snippet.

---

## Sources

- [Ollama Embedding Models Comparison](https://elephas.app/blog/best-embedding-models)
- [FastEmbed: Lightweight ONNX Embeddings](https://github.com/qdrant/fastembed)
- [USearch: Single-File Vector Search](https://github.com/unum-cloud/USearch)
- [sqlite-vec: Vector Search for SQLite](https://github.com/asg017/sqlite-vec)
- [FAISS vs HNSWlib Comparison](https://zilliz.com/blog/faiss-vs-hnswlib-choosing-the-right-tool-for-vector-search)
- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
- [Claude Code MCP Integration](https://code.claude.com/docs/en/mcp)
- [Claude Context: Semantic Code Search MCP](https://github.com/zilliztech/claude-context)
- [Qdrant MCP Server](https://github.com/qdrant/mcp-server-qdrant)
- [Hybrid BM25 + Vector Search](https://medium.com/@aunraza021/combining-bm25-vector-search-a-hybrid-approach-for-enhanced-retrieval-performance-a374b4ba4644)
- [Sentence Transformers ONNX Optimization](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)
- [Voyage AI Pricing](https://docs.voyageai.com/docs/pricing)
- [Apple CoreML Models](https://developer.apple.com/machine-learning/models/)
- [llama.cpp Embedding Server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
