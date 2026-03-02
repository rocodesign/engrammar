# Engrammar Architecture

Comprehensive technical documentation for the Engrammar semantic knowledge system.

## Table of Contents

- [Overview](#overview)
- [Core Components](#core-components)
- [Tag System](#tag-system)
- [Auto-Pin Algorithm](#auto-pin-algorithm)
- [Search Architecture](#search-architecture)
- [Hook System](#hook-system)
- [Daemon System](#daemon-system)
- [Database Schema](#database-schema)
- [MCP Integration](#mcp-integration)
- [Performance](#performance)
- [Extraction Pipeline](#extraction-pipeline)
- [Dedup Pipeline](#dedup-pipeline)
- [Data Flow](#data-flow)

---

## Overview

Engrammar is a semantic knowledge system that learns from Claude Code sessions and intelligently surfaces relevant engrams. The system uses:

1. **Tag-based environment detection** - Automatically understands project context
2. **Hybrid search** - Combines vector similarity and BM25 keyword matching
3. **Tag relevance scoring** - EMA-based per-tag scores filter irrelevant engrams dynamically
4. **Smart auto-pinning** - Learns which engrams are universally valuable
5. **Hook integration** - Surfaces engrams at the perfect moment
6. **MCP server** - Enables direct Claude interaction

### Key Innovation

The **tag subset algorithm** enables cross-project learning:

- Engram matches 6x in `['acme', 'frontend', 'typescript']`
- Engram matches 5x in `['acme', 'frontend', 'react']`
- Engram matches 4x in `['personal', 'frontend', 'typescript']`
- **Algorithm finds**: `['frontend']` has 15 total matches -> auto-pin
- **Result**: Engram now shows in ALL frontend projects, not just specific repos

---

## Core Components

### 1. Environment Detection

> Source: [`src/environment.py`](../src/environment.py), [`src/tag_detectors.py`](../src/tag_detectors.py), [`src/tag_patterns.py`](../src/tag_patterns.py)

Returns `{os, repo, cwd, mcp_servers, tags}` by combining five detection sources:

| Source | File | Examples |
|--------|------|----------|
| Path patterns | `tag_patterns.py` | `/work/acme/*` -> `acme` |
| Git remotes | `tag_patterns.py` | `github.com/acme` -> `github`, `acme` |
| File markers | `tag_patterns.py` | `tsconfig.json` -> `typescript` |
| Dependencies | `tag_patterns.py` | `"react"` in package.json -> `react`, `frontend` |
| Directory structure | `tag_patterns.py` | `packages/` -> `monorepo` |

### 2. Database Layer

> Source: [`src/db.py`](../src/db.py)

SQLite with WAL mode for concurrent access. Key functions:

- **Engram management**: `add_engram()`, `get_all_active_engrams()`, `deprecate_engram()`
- **Match statistics**: `update_match_stats()` — updates global counter, per-repo stats, per-tag-set stats, and checks auto-pin threshold
- **Auto-pin detection**: `find_auto_pin_tag_subsets()` — returns minimal common tag subset with threshold+ matches
- **Tag relevance**: `update_tag_relevance()` — EMA-based per-tag scoring with auto-pin/unpin decisions

### 3. Search Engine

> Source: [`src/search.py`](../src/search.py)

Hybrid search combining vector similarity and BM25. See [Search Architecture](#search-architecture) for the full pipeline.

### 4. Embeddings

> Source: [`src/embeddings.py`](../src/embeddings.py)

Uses `BAAI/bge-small-en-v1.5` (384 dimensions) via `fastembed` for local, API-free embedding. The model is lazy-loaded and cached after first call.

**Index files** (all numpy `.npy`, memory-mapped with `mmap_mode="r"` for zero-copy access):

| File | Contents |
|------|----------|
| `embeddings.npy` | Engram text embeddings (N x 384) |
| `embedding_ids.npy` | Engram IDs mapping (N,) |
| `tag_embeddings.npy` | Prerequisite tag embeddings |
| `tag_embedding_ids.npy` | Engram IDs for tag embeddings |

---

## Tag System

### Tag Detection Pipeline

```
Environment -> Path + Git + Files + Deps + Structure -> Unique Sorted Tags
```

Example in `~/work/acme/app-repo`:

```
Path:     [acme]
Git:      [github, acme]
Files:    [typescript, nodejs, docker, jest]
Deps:     [react, frontend, tailwind, davinci, testing]
Struct:   [monorepo, frontend]

-> Merged: [davinci, docker, frontend, github, jest, monorepo,
           nodejs, tailwind, react, testing, acme, typescript]
```

### Prerequisites

Stored in `engrams.prerequisites` as JSON:

```json
{
  "tags": ["frontend", "react"],
  "repos": ["app-repo"],
  "os": ["darwin"]
}
```

**Two types of prerequisites:**

- **Structural** (`os`, `repos`, `paths`, `mcp_servers`) — hard-gated via `check_structural_prerequisites()` in [`src/environment.py`](../src/environment.py). Physical constraints that are always enforced.
- **Tags** — **not hard-gated**. Tag relevance scoring handles context filtering dynamically. A engram with `{"tags": ["acme"]}` can appear anywhere; the evaluator learns where it's relevant.

See [evaluation.md](evaluation.md) for how tag relevance scores work.

---

## Auto-Pin Algorithm

> Source: [`src/db.py`](../src/db.py) — `find_auto_pin_tag_subsets()`, `update_match_stats()`

### Problem

Repo-based auto-pin limits cross-project learning. An engram with 15 matches in `app-repo` pins only to `app-repo` — the same engram valuable in other frontend projects starts from 0 matches.

### Solution: Tag Subset Auto-Pin

Finds minimal common tags across different tag sets. Steps:

1. Get all `tag_sets` where engram matched (from `engram_tag_stats`)
2. Generate powerset of all unique tags (limit size=4 for performance)
3. Count matches for each subset across all tag_sets
4. Find minimal subsets (no proper subset also meets threshold)
5. Return smallest minimal subset

### Example

```
tag_set_1: ['frontend', 'acme', 'typescript'], matches: 6
tag_set_2: ['frontend', 'acme', 'react'], matches: 5
tag_set_3: ['frontend', 'personal', 'typescript'], matches: 4

Candidates (size 1):
  {frontend}: 6 + 5 + 4 = 15  (meets threshold)
  {acme}: 6 + 5 = 11
  {typescript}: 6 + 4 = 10

-> Output: ['frontend']
-> Engram auto-pins with {"tags": ["frontend"]}
```

### Trigger

Called from `update_match_stats()` after incrementing per-tag-set counters. If a qualifying subset is found and the engram isn't already pinned, it sets `pinned=1` with the tag prerequisite.

---

## Search Architecture

> Source: [`src/search.py`](../src/search.py)

### Query Flow

```
User Query
    |
1. Load ALL Active Engrams
    |
2. Parallel Search:
   +-- Vector Search (fastembed, BAAI/bge-small-en-v1.5, 384 dims)
   +-- BM25 Keyword Search (rank_bm25.BM25Okapi, tokenized with \w+ regex)
    |
3. Reciprocal Rank Fusion (dynamic k = max(1, len(engrams) // 5))
    |
3.1. Tag Affinity Boost (cosine similarity of env tags vs engram tags)
     0.3x penalty -> 1.0x neutral -> 1.7x boost
    |
3.5. Tag Relevance Filter + Boost
     (filter strong negatives, boost positives via EMA scores)
    |
4. Apply Category Filter
    |
4.5. Apply Tag Filter
    |
5. Return Top K (default: 3 from config)
```

### Reciprocal Rank Fusion

**Formula**: `score(item) = Sum(1 / (k + rank))` where k is dynamic: `max(1, len(engrams) // 5)`.

Standard k=60 compresses small engram sets into a ~15% spread. Dynamic k gives ~2x spread between rank 0 and rank 9, which better discriminates among small corpora.

### Tag Affinity Boost (step 3.1)

Uses precomputed tag embeddings (`tag_embeddings.npy`) for vectorized cosine similarity. Compares the environment tag embedding against each engram's prerequisite tag embedding.

- `sim ~0.65` (unrelated stack) -> ~0.3x penalty
- `sim ~0.80` (partial match) -> ~1.0x neutral
- `sim ~0.95+` (same stack) -> ~1.7x boost

Engrams without prerequisite tags are treated as neutral (no boost/penalty). Falls back to per-engram embedding if the tag index isn't built yet.

### Tag Relevance Filter (step 3.5)

See [evaluation.md](evaluation.md) for full details. Uses constants from `search.py`:

- `MIN_EVALS_FOR_FILTER = 3` — need evidence before filtering
- `NEGATIVE_SCORE_THRESHOLD = -0.1` — filter if avg below this
- `RELEVANCE_WEIGHT = 0.01` — boost/penalty weight on RRF score

---

## Hook System

> Source: [`hooks/`](../hooks/)

### Hook Lifecycle

```
SessionStart -> UserPromptSubmit -> PreToolUse -> (tool execution) -> Stop
```

| Hook | File | Trigger | Purpose |
|------|------|---------|---------|
| SessionStart | [`on_session_start.py`](../hooks/on_session_start.py) | Session begins | Inject pinned engrams, start daemon, run maintenance, clean up stale offsets |
| UserPromptSubmit | [`on_prompt.py`](../hooks/on_prompt.py) | User sends a prompt | Search engrams relevant to the prompt |
| PreToolUse | [`on_tool_use.py`](../hooks/on_tool_use.py) | Before tool execution | Search engrams relevant to the tool being used |
| Stop | [`on_stop.py`](../hooks/on_stop.py) | After each assistant response | Write session audit, trigger per-turn extraction (+ evaluation on separate proc) |

### SessionStart

Loads pinned engrams, hard-gates on structural prerequisites, soft-gates on tag relevance (filters if `evals >= 3` and `avg < -0.1`). Also starts the daemon, triggers maintenance jobs, and cleans up stale turn offset files (>24h old).

### UserPromptSubmit

Searches engrams relevant to the user's prompt text. Tries daemon for fast search (~20ms), falls back to direct search. Filters out already-shown engrams (DB-based, keyed by session ID). Logs events to `hook_event_log`.

### PreToolUse

Extracts keywords from `tool_name` + `tool_input` (file paths, commands) and runs hybrid search. Skips tools in the `skip_tools` config list. Same daemon/fallback/dedup pattern as UserPromptSubmit.

### Stop

Fires after every assistant response for incremental, reliable extraction. Writes session audit record with shown engram IDs, env tags, and transcript path. Sends `process_turn` request to the daemon, which spawns a background `process-turn` CLI job. Falls back to direct `subprocess.Popen` if daemon is unavailable. Skips subagent sessions. Uses byte offsets to only process new transcript content since the last turn — see [Extraction Pipeline](#extraction-pipeline).

---

## Daemon System

> Source: [`src/daemon.py`](../src/daemon.py), [`src/client.py`](../src/client.py)

Keeps the embedding model warm in memory for fast hook searches.

```
SessionStart hook
    -> client.py: send_request({"type": "run_maintenance"})
    -> Starts daemon if not running (Unix domain socket)
    -> Daemon loads model + indexes into memory

UserPromptSubmit / PreToolUse hook
    -> client.py: send_request({"type": "search", "query": "..."})
    -> Daemon responds in ~20ms (vs ~500ms cold start)
```

| Request Type | Purpose |
|------|---------|
| `search` | Hybrid search for a query (used by UserPromptSubmit) |
| `tool_context` | Tool-specific search (used by PreToolUse) |
| `process_turn` | Per-turn extraction (used by Stop hook) — coalescing queue with single-flight via `extract_proc` |
| `run_maintenance` | Trigger background jobs (index rebuild, extraction) |

The daemon listens on a Unix socket at `~/.engrammar/daemon.sock`. Auto-started by SessionStart hook. Hooks fall back to direct search if the daemon is unavailable.

---

## Database Schema

> Source: [`src/db.py`](../src/db.py) — `init_db()`

### Tables

#### `engrams`

```sql
CREATE TABLE engrams (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    level1 TEXT,
    level2 TEXT,
    level3 TEXT,
    source TEXT DEFAULT 'manual',
    source_sessions TEXT DEFAULT '[]',
    occurrence_count INTEGER DEFAULT 1,
    times_matched INTEGER DEFAULT 0,
    last_matched TEXT,
    created_at TEXT,
    updated_at TEXT,
    deprecated INTEGER DEFAULT 0,
    prerequisites TEXT DEFAULT NULL,
    pinned INTEGER DEFAULT 0,
    dedup_verified INTEGER DEFAULT 0,
    dedup_attempts INTEGER DEFAULT 0,
    dedup_last_error TEXT DEFAULT NULL
);
```

#### `engram_repo_stats`

Per-repo match tracking. `PRIMARY KEY (engram_id, repo)`.

#### `engram_tag_stats`

Per-tag-set match tracking. `tag_set` is a JSON array (e.g. `'["frontend", "react"]'`). `PRIMARY KEY (engram_id, tag_set)`.

#### `engram_tag_relevance`

Per-tag EMA relevance scores. `score` is EMA-smoothed, `positive_evals`/`negative_evals` track evidence count. `PRIMARY KEY (engram_id, tag)`.

#### `session_audit`

Ground truth for what was shown per session. Stores `shown_engram_ids` (JSON), `env_tags` (JSON), `repo`, `transcript_path`.

#### `processed_relevance_sessions`

Evaluation pipeline tracking. `status`: `'pending'` | `'completed'` | `'failed'`, with `retry_count`.

#### `hook_event_log`

Persistent event log for hook activity. Stores `hook_event` (SessionStart/UserPromptSubmit/PreToolUse), `engram_ids` (JSON), and `context`.

#### `session_shown_engrams`

Tracks which engrams were shown during a session (replaces the old `.session-shown.json` file). `UNIQUE(session_id, engram_id)`.

#### `processed_sessions`

Tracks which sessions have been processed by the extraction pipeline.

#### `categories`

Category path tree. `path TEXT PRIMARY KEY`.

#### `engram_categories`

Junction table for multi-category engrams. `PRIMARY KEY (engram_id, category_path)`.

#### `engram_merge_log`

Audit log for dedup merges. Stores `run_id`, `survivor_id`, `absorbed_ids` (JSON array), `canonical_text`, `confidence`, `reason`, and `created_at`.

---

## MCP Integration

> Source: [`src/mcp_server.py`](../src/mcp_server.py)

### Server Configuration

```json
{
  "mcpServers": {
    "engrammar": {
      "command": "/Users/user/.engrammar/venv/bin/python",
      "args": ["/Users/user/.engrammar/engrammar/mcp_server.py"],
      "env": { "ENGRAMMAR_HOME": "/Users/user/.engrammar" }
    }
  }
}
```

### Available Tools (10)

| Tool | Parameters | Purpose |
|------|-----------|---------|
| `engrammar_search` | `query`, `category?`, `tags?`, `top_k?` | Semantic + keyword search |
| `engrammar_add` | `text`, `category?`, `tags?`, `prerequisites?`, `source?` | Add new engram |
| `engrammar_update` | `engram_id`, `text?`, `category?`, `prerequisites?` | Update existing engram |
| `engrammar_deprecate` | `engram_id`, `reason?` | Soft-delete engram |
| `engrammar_feedback` | `engram_id`, `applicable`, `reason?`, `tag_scores?`, `add_prerequisites?` | Record relevance feedback |
| `engrammar_categorize` | `engram_id`, `add?`, `remove?` | Manage multi-category membership |
| `engrammar_pin` | `engram_id`, `prerequisites?` | Pin for session start injection |
| `engrammar_unpin` | `engram_id` | Unpin engram |
| `engrammar_list` | `category?`, `include_deprecated?`, `limit?`, `offset?` | List/browse engrams |
| `engrammar_status` | (none) | System health check |

---

## Performance

### Benchmarks

| Operation | Time | Details |
|-----------|------|---------|
| Tag detection | <30ms | 5 sources, ~1000 files scanned |
| Tag subset algorithm | <20ms | Powerset generation + counting |
| Vector embedding | ~50ms | Local fastembed model |
| Search (hybrid) | ~100ms | Vector + BM25 + RRF |
| Tag filtering | <5ms | Set intersection operations |
| Session start hook | ~100ms | Load + filter pinned engrams |
| Database write | <10ms | WAL mode, concurrent-safe |

### Memory Usage

| Component | Size |
|-----------|------|
| Embeddings index (1000 engrams) | ~2MB |
| Engram metadata | ~500KB |
| Tag stats (10 tag sets/engram) | ~50KB |
| BM25 index | ~1MB |
| **Total** | **~3.5MB** |

---

## Extraction Pipeline

> Source: [`src/extractor.py`](../src/extractor.py)

Engrams are automatically extracted from Claude Code conversation transcripts (JSONL files in `~/.claude/projects/`). The extractor sends conversation content to Haiku for analysis, looking specifically for **friction moments** — not task summaries.

### Extraction Criteria

The prompt instructs Haiku to **only** extract from friction patterns:

1. **User corrections** — assistant tried A, user said "no, do B"
2. **Repeated struggle** — multiple turns on something avoidable
3. **Discovered conventions** — user revealed a project rule
4. **Tooling gotchas** — unexpected tool/API behavior

Explicitly rejected: task instructions, build summaries, generic advice, implementation details.

### Per-Transcript Pipeline (Batch)

```
For each transcript (oldest-first):
    1. Read metadata -> extract cwd, repo
    2. Detect env tags by chdir to transcript's cwd
    3. Write session_audit record
    4. Read existing CLAUDE.md/AGENTS.md to avoid duplicating documented knowledge
    5. Send transcript text + instructions to Haiku
    6. Parse JSON array response
    7. For each extracted engram:
       a. Infer prerequisites from text + project signals
       b. Enrich with session env tags
       c. Check dedup (embedding similarity 0.85, word overlap 0.70 fallback)
       d. Initialize tag relevance scores from env tags
    8. Mark session as processed
    9. Rebuild embedding index (for next transcript's dedup)
```

### Per-Turn Pipeline (Incremental)

The Stop hook triggers `extract_from_turn()` after each assistant response, using byte offsets to process only new content:

```
Stop hook fires:
    1. Read byte offset from ~/.engrammar/.turn_offsets/<session_id>
    2. Read new messages from transcript JSONL starting at offset
    3. Skip if transcript < 10KB or new content < 50 chars
    4. Read ~2000 chars of prior context for continuity
    5. Get metadata + env tags, write session_audit
    6. Send [context + new content] to Haiku for extraction
    7. Process results (dedup via find_similar_engram)
    8. Rebuild index if new engrams added
    9. Save new byte offset
```

**Concurrency**: The daemon maintains a coalescing queue (`_pending_turns`) for turn extraction. Only one `extract_proc` runs at a time. If the Stop hook fires while extraction is running, the request is queued (coalesced per session — latest transcript path wins). When extraction finishes, `_drain_pending_turns()` starts the next pending session. Drain runs after each connection and on 5s timeout polls. Byte offsets ensure each drain run catches all accumulated content since the last processed turn.

**State**: Turn offsets are stored as plain integers in `~/.engrammar/.turn_offsets/<session_id>`. Cleaned up by SessionStart hook (files >24h old).

### Automatic Extraction

The Stop hook triggers background extraction after each assistant response via the daemon's `process_turn` handler. Extraction runs on `extract_proc`, evaluation runs concurrently on `evaluate_proc`. Falls back to direct `subprocess.Popen` if the daemon is unavailable.

---

## Dedup Pipeline

> Source: [`src/dedup.py`](../src/dedup.py), [`src/db.py`](../src/db.py) — `merge_engram_group()`

### Problem

The inline dedup (`find_similar_engram` at 0.85 embedding / 0.70 word-overlap) only catches near-identical text. Conceptual duplicates — same lesson expressed differently across sessions — slip through.

### Pipeline Flow

```
engrammar dedup
    |
1. Bootstrap Detection
   Verified pool < 3? -> Bootstrap mode (all-vs-all)
   Otherwise         -> Incremental mode (unverified-vs-verified)
    |
2. Candidate Finding (vectorized cosine similarity)
   For each unverified engram, find top_k verified candidates above min_sim (0.50)
    |
3. Batch Building
   Group unverified+candidate pairs into batches respecting character budget
   Shared verified candidates across pairs give Haiku cross-pair visibility
    |
4. LLM Call (Haiku)
   Send batch with system prompt + mode snippet + JSON payload
   Returns: groups (ids, canonical_text, confidence, reason) + no_match_ids
    |
5. Strict Validation
   All IDs exist, no duplicates, group size >= 2, confidence in [0,1]
   Every unverified ID accounted for (in a group or no_match_ids)
    |
6. Merge Execution (transactional per group)
   Update survivor text, merge stats, rewrite linked tables
   Deprecate absorbed engrams
    |
7. Re-queue Survivor (dedup_verified = 0)
   Changed text/embedding may enable further merges
    |
8. Multi-pass Loop
   Rebuild embedding index, re-run until zero merges or max_passes
```

### Modes

- **Incremental**: Unverified engrams are paired only against verified candidates. Prevents bridge destruction (if A and B are verified but don't match each other, unverified C and D matching A and B respectively stay independent).
- **Bootstrap**: When the verified pool is too small, all active engrams are compared. Avoids "first processed wins" order sensitivity.

### Merge Semantics

Deterministic survivor selection: prefer verified > highest `occurrence_count` > lowest ID.

All operations transactional on a single connection:

| Table | Merge behavior |
|-------|---------------|
| `engrams` | Update text, sum occurrence_count, union sessions, re-queue |
| `prerequisites.tags` | Intersection (AND-gated) |
| `prerequisites.repos` | Union (OR semantics) |
| `prerequisites.mcp_servers` | Intersection (AND semantics) |
| `engram_categories` | Union |
| `engram_repo_stats` | Sum per-repo counts |
| `engram_tag_stats` | Sum per-tag-set counts |
| `engram_tag_relevance` | Evidence-weighted average score, sum eval counters |
| `session_shown_engrams` | Rewrite absorbed IDs to survivor |
| `session_audit.shown_engram_ids` | JSON rewrite |
| `hook_event_log.engram_ids` | JSON rewrite |
| `engram_merge_log` | Audit log entry |

### DB Columns

Added to `engrams`:

- `dedup_verified INTEGER DEFAULT 0` — processing state (0=pending, 1=verified)
- `dedup_attempts INTEGER DEFAULT 0` — retry counter
- `dedup_last_error TEXT` — last failure message

Index: `idx_engrams_dedup_queue ON engrams(deprecated, dedup_verified, id)`

### Invariants

- Every merge is atomic (single transaction, rollback on failure).
- Survivors are always re-queued after merge.
- Absorbed engrams are deprecated + marked verified (never reprocessed).
- The inline 0.85 threshold check at insertion time stays — dedup catches what it misses.
- Failed LLM calls are retryable (increment attempts, preserve error).

---

## Data Flow

### Engram Lifecycle

```
1. Creation
   Transcript JSONL -> extractor -> Haiku analysis -> add_engram() -> DB
   OR: User -> CLI/MCP -> add_engram() -> DB

2. Indexing
   DB -> build_index() -> .npy files (content + tag embeddings)

3. Matching
   SessionStart/UserPromptSubmit/PreToolUse -> search() -> RRF -> tag affinity boost -> tag relevance filter -> results

4. Tracking
   Stop hook -> record audit -> evaluator -> tag relevance scores (EMA)

5. Dedup (CLI or scheduled)
   engrammar dedup -> find candidates -> Haiku judgment -> merge duplicates -> rebuild index

6. Auto-Pin
   update_match_stats() -> find_auto_pin_tag_subsets() -> threshold reached -> pinned=1
   OR: tag relevance avg > 0.6 with enough evidence -> auto-pin

7. Filtering (next session)
   search() -> tag relevance scores filter strong negatives, boost positives
```

---

## Security Considerations

**No API key required for core functionality**: tag detection (filesystem/git), embeddings (local fastembed), search (local), auto-pin (local algorithm), session end (fail-open).

**Optional AI evaluation**: session end evaluation + extraction use Haiku (requires `ANTHROPIC_API_KEY`). Gracefully falls back without it.

**File access**: reads files in CWD only, git read-only, writes only to `~/.engrammar/`.

**SQL injection**: all queries use parameterized statements, JSON validated before parsing.

---

## Glossary

| Term | Definition |
|------|------------|
| **Tag** | Environment identifier (e.g., 'frontend', 'acme', 'react') |
| **Tag Set** | Sorted list of tags for an environment |
| **Tag Subset** | Smaller set contained within multiple tag sets |
| **Auto-Pin** | Automatic marking of engrams as always-show when threshold reached |
| **Prerequisite** | Condition for showing a engram (repo, os, tags, etc.) |
| **RRF** | Reciprocal Rank Fusion - algorithm for merging ranked lists |
| **BM25** | Best Matching 25 - probabilistic relevance ranking |
| **MCP** | Model Context Protocol - Claude's tool integration system |
| **EMA** | Exponential Moving Average - smoothing for tag relevance scores |
| **Daemon** | Long-running process that keeps model warm for fast hook searches |

---

## References

- [BM25 Algorithm](https://en.wikipedia.org/wiki/Okapi_BM25)
- [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- [FastEmbed](https://github.com/qdrant/fastembed) — local embedding via BAAI/bge-small-en-v1.5
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
