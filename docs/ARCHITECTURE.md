# Engrammar Architecture

Comprehensive technical documentation for the Engrammar semantic knowledge system.

## Table of Contents

- [Overview](#overview)
- [Core Components](#core-components)
- [Tag System](#tag-system)
- [Auto-Pin Algorithm](#auto-pin-algorithm)
- [Search Architecture](#search-architecture)
- [Hook System](#hook-system)
- [Database Schema](#database-schema)
- [MCP Integration](#mcp-integration)
- [Performance](#performance)
- [Extraction Pipeline](#extraction-pipeline)
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

- Engram matches 6× in `['acme', 'frontend', 'typescript']`
- Engram matches 5× in `['acme', 'frontend', 'react']`
- Engram matches 4× in `['personal', 'frontend', 'typescript']`
- **Algorithm finds**: `['frontend']` has 15 total matches → auto-pin
- **Result**: Engram now shows in ALL frontend projects, not just specific repos

---

## Core Components

### 1. Environment Detection (`environment.py`)

Detects current environment context from multiple sources.

```python
def detect_environment() -> dict:
    return {
        "os": platform.system().lower(),
        "repo": _detect_repo(),
        "cwd": os.getcwd(),
        "mcp_servers": _detect_mcp_servers(),
        "tags": detect_tags()  # NEW
    }
```

#### Tag Detection (`tag_detectors.py`)

Five detection sources:

**A. Path Patterns**

```python
PATH_PATTERNS = [
    (re.compile(r"/work/acme/"), "acme"),
    (re.compile(r"/work/app\.mo\.de"), "personal"),
]
```

**B. Git Remotes**

```python
GIT_REMOTE_PATTERNS = [
    (re.compile(r"github\.com"), "github"),
    (re.compile(r"github\.com[:/]acme/"), "acme"),
]
```

**C. File Markers**

```python
FILE_MARKERS = {
    "tsconfig.json": ["typescript"],
    "package.json": ["nodejs"],
    "Gemfile": ["ruby"],
    "Dockerfile": ["docker"],
}
```

**D. package.json Dependencies**

```python
PACKAGE_DEPENDENCY_TAGS = {
    "react": ["react", "frontend"],
    "next": ["nextjs", "react", "frontend"],
    "@acme/library-name": ["acme", "library-name", "react", "frontend"],
}
```

**E. Directory Structure**

```python
DIR_STRUCTURE_PATTERNS = {
    "engines/": ["monorepo", "rails-engines"],
    "packages/": ["monorepo"],
    "components/": ["frontend", "react"],
}
```

### 2. Database Layer (`db.py`)

SQLite with WAL mode for concurrent access.

#### Core Functions

**Engram Management**

```python
add_engram(text, category, tags=None, source="manual")
get_all_active_engrams()
deprecate_engram(engram_id)
```

**Match Statistics**

```python
update_match_stats(engram_id, repo=None, tags=None)
# Updates:
# - Global counter: engrams.times_matched
# - Per-repo stats: engram_repo_stats
# - Per-tag-set stats: engram_tag_stats (NEW)
# - Checks auto-pin threshold
```

**Auto-Pin Detection**

```python
find_auto_pin_tag_subsets(engram_id, threshold=15)
# Returns: minimal common tag subset with threshold+ matches
```

### 3. Search Engine (`search.py`)

Hybrid search combining vector similarity and BM25.

```python
def search(query, category_filter=None, tag_filter=None, top_k=5):
    # 1. Load ALL active engrams (no prerequisite hard-gating)
    engrams = get_all_active_engrams()
    env = detect_environment()

    # 2. Vector search (embeddings)
    query_embedding = embed_text(query)
    vector_results = vector_search(query_embedding, embeddings, ids, top_k=10)

    # 3. BM25 keyword search
    bm25_scores = bm25.get_scores(tokenize(query))
    bm25_ranked = sorted(zip(ids, bm25_scores), reverse=True)[:10]

    # 4. Reciprocal Rank Fusion
    fused = _reciprocal_rank_fusion([vector_results, bm25_ranked])

    # 5. Tag relevance filter + boost
    #    - Filter: remove engrams with strong negative signal (avg < -0.1, evals >= 3)
    #    - Boost: adjust RRF score by tag relevance
    #    See: docs/evaluation.md for full details
    if env.get("tags"):
        for engram in fused:
            avg, evals = get_tag_relevance_with_evidence(engram.id, env["tags"])
            if evals >= 3 and avg < -0.1:
                remove(engram)  # strong negative = filter out
            else:
                engram.score += (avg / 3.0) * 0.01  # boost/penalize

    # 6. Apply category filter
    if category_filter:
        fused = [f for f in fused if matches_category(f, category_filter)]

    # 7. Apply tag filter (explicit tag_filter parameter, not env-based)
    if tag_filter:
        fused = [f for f in fused if has_all_tags(f, tag_filter)]

    return fused[:top_k]
```

#### Reciprocal Rank Fusion

```python
def _reciprocal_rank_fusion(ranked_lists, k=60):
    scores = {}
    for ranked_list in ranked_lists:
        for rank, (item_id, _) in enumerate(ranked_list):
            scores[item_id] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

### 4. Embeddings (`embeddings.py`)

Uses Anthropic's `voyage-3-lite` model for semantic search.

```python
def embed_text(text: str) -> list[float]:
    """Generate 512-dim embedding vector."""
    response = anthropic.Anthropic().embeddings.create(
        model="voyage-3-lite",
        input=text
    )
    return response.embeddings[0]

def build_index(engrams: list[dict]) -> int:
    """Build numpy array of embeddings for all engrams."""
    embeddings = np.array([embed_text(l["text"]) for l in engrams])
    np.save(INDEX_PATH, embeddings)
    with open(IDS_PATH, "w") as f:
        json.dump([l["id"] for l in engrams], f)
    return len(engrams)
```

---

## Tag System

### Tag Detection Pipeline

```
Environment → Path + Git + Files + Deps + Structure → Unique Sorted Tags
```

Example: `~/work/acme/app-repo`

```
Path:     [acme]
Git:      [github, acme]
Files:    [typescript, nodejs, docker, jest]
Deps:     [react, frontend, tailwind, davinci, testing]
Struct:   [monorepo, frontend]

→ Merged: [davinci, docker, frontend, github, jest, monorepo,
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

- **Structural** (`os`, `repos`, `paths`, `mcp_servers`) — hard-gated via `check_structural_prerequisites()`. Physical constraints that are always enforced.
- **Tags** — **not hard-gated**. Tag relevance scoring handles context filtering dynamically. A engram with `{"tags": ["acme"]}` can appear anywhere; the evaluator learns where it's relevant and accumulates scores that filter it from irrelevant contexts.

```python
def check_structural_prerequisites(prerequisites, env):
    """Checks os, repo, paths, mcp_servers. Ignores tags."""
    structural = {k: v for k, v in prerequisites.items() if k != "tags"}
    return check_prerequisites(structural, env)
```

See [evaluation.md](evaluation.md) for how tag relevance scores work.

---

## Auto-Pin Algorithm

### Problem Statement

Repo-based auto-pin limits cross-project learning:

- Engram with 15 matches in `app-repo` → pins to `app-repo` only
- Same engram valuable in `tailwind` but starts from 0 matches

### Solution: Tag Subset Auto-Pin

Find minimal common tags across different tag sets.

### Algorithm

```python
def find_auto_pin_tag_subsets(engram_id, threshold=15):
    """Find minimal common tag subset with threshold+ matches.

    Steps:
    1. Get all tag_sets where engram matched
    2. Generate powerset of all unique tags (limit size=4 for performance)
    3. Count matches for each subset across all tag_sets
    4. Find minimal subsets (no proper subset also meets threshold)
    5. Return smallest minimal subset
    """

    # 1. Get all tag sets
    rows = db.execute("""
        SELECT tag_set, times_matched
        FROM engram_tag_stats
        WHERE engram_id = ?
    """, (engram_id,))

    tag_sets = [(set(json.loads(r["tag_set"])), r["times_matched"]) for r in rows]
    all_tags = set().union(*[ts for ts, _ in tag_sets])

    # 2. Generate powerset (limit to size 4)
    from itertools import combinations
    candidates = []
    for r in range(1, min(len(all_tags), 4) + 1):
        candidates.extend([set(c) for c in combinations(sorted(all_tags), r)])

    # 3. Count matches for each subset
    subset_counts = {}
    for candidate in candidates:
        total = sum(count for tag_set, count in tag_sets if candidate.issubset(tag_set))
        if total >= threshold:
            subset_counts[frozenset(candidate)] = total

    if not subset_counts:
        return None

    # 4. Find minimal subsets
    sorted_subsets = sorted(subset_counts.keys(), key=len)
    minimal = []
    for subset in sorted_subsets:
        if not any(other < subset for other in minimal):
            minimal.append(subset)

    # 5. Return smallest
    return sorted(list(min(minimal, key=len)))
```

### Example Execution

**Input**: 3 tag sets with matches

```
tag_set_1: ['frontend', 'acme', 'typescript'], matches: 6
tag_set_2: ['frontend', 'acme', 'react'], matches: 5
tag_set_3: ['frontend', 'personal', 'typescript'], matches: 4
```

**Process**:

```
all_tags = {frontend, acme, typescript, react, personal}

Candidates (size 1):
  {frontend}: 6 + 5 + 4 = 15 ✓
  {acme}: 6 + 5 = 11 ✗
  {typescript}: 6 + 4 = 10 ✗
  {react}: 5 ✗
  {personal}: 4 ✗

Candidates (size 2):
  {frontend, acme}: 6 + 5 = 11 ✗
  ... (all below threshold)

Minimal subsets: [{frontend}]
```

**Output**: `['frontend']`

### Auto-Pin Trigger

```python
def update_match_stats(engram_id, repo=None, tags=None):
    # ... update counters ...

    if tags:
        # After updating tag_set stats
        auto_pin_tags = find_auto_pin_tag_subsets(engram_id)
        if auto_pin_tags:
            engram = get_engram(engram_id)
            if not engram["pinned"]:
                # Auto-pin with tag prerequisite
                prereqs = json.loads(engram["prerequisites"] or "{}")
                prereqs["tags"] = auto_pin_tags
                db.execute("""
                    UPDATE engrams
                    SET pinned = 1, prerequisites = ?
                    WHERE id = ?
                """, (json.dumps(prereqs), engram_id))
```

---

## Search Architecture

### Query Flow

```
User Query
    ↓
1. Load ALL Active Engrams
    ↓
2. Parallel Search:
   ├─ Vector Search (Voyage embeddings)
   └─ BM25 Keyword Search
    ↓
3. Reciprocal Rank Fusion (merge results)
    ↓
4. Tag Relevance Filter + Boost
   (filter strong negatives, boost positives)
    ↓
5. Apply Category Filter
    ↓
6. Apply Tag Filter
    ↓
7. Return Top K
```

### Vector Search

**Model**: `voyage-3-lite` (512 dimensions)
**Index**: Numpy array of embeddings (`.npy`)

```python
def vector_search(query_embedding, embeddings, ids, top_k=10):
    # Cosine similarity via dot product (normalized embeddings)
    scores = np.dot(embeddings, query_embedding)
    top_indices = np.argsort(scores)[-top_k:][::-1]
    return [(ids[i], float(scores[i])) for i in top_indices]
```

### BM25 Search

**Implementation**: `rank_bm25.BM25Okapi`
**Tokenization**: Simple regex `\w+`

```python
def _tokenize(text):
    return re.findall(r"\w+", text.lower())

corpus = [tokenize(l["text"] + " " + l["category"]) for l in engrams]
bm25 = BM25Okapi(corpus)
scores = bm25.get_scores(tokenize(query))
```

### Reciprocal Rank Fusion

**Formula**: `score(item) = Σ(1 / (k + rank))`
**Default k**: 60

**Why RRF?**

- Handles score scale differences between vector and BM25
- Emphasizes top-ranked items
- Simple and effective for result merging

---

## Hook System

### Hook Lifecycle

```
SessionStart → UserPromptSubmit → PreToolUse → (tool execution) → PostToolUse → SessionEnd
```

### SessionStart Hook

```python
def on_session_start():
    env = detect_environment()
    env_tags = env.get("tags", [])

    pinned = get_pinned_engrams()
    matching = []
    for p in pinned:
        # Hard-gate on structural prerequisites (os, repo, paths, mcp_servers)
        if not check_structural_prerequisites(p["prerequisites"], env):
            continue
        # Soft-gate on tag relevance
        if env_tags:
            avg, evals = get_tag_relevance_with_evidence(p["id"], env_tags)
            if evals >= 3 and avg < -0.1:
                continue
        matching.append(p)

    if matching:
        print("Relevant engrams from past sessions:")
        for engram in matching:
            print(f"- [{engram['category']}] {engram['text']}")
```

### PreToolUse Hook

```python
def on_tool_use(tool_name, tool_input):
    # Extract keywords
    keywords = [tool_name]
    if isinstance(tool_input, dict):
        for key in ("file_path", "path", "command"):
            if val := tool_input.get(key):
                keywords.append(val)

    # Search for relevant engrams
    query = " ".join(keywords)
    results = search(query, top_k=2)

    # Track shown engrams (for session end)
    track_shown(results)

    # Format output
    if results:
        print(f"\nRelevant engrams for {tool_name}:")
        for engram in results:
            print(f"- {engram['text']}")
```

### SessionEnd Hook

**Purpose**: Track which engrams were actually useful

```python
def on_session_end(session_data):
    # Get engrams shown during session
    shown_ids = load_shown()

    # Get environment tags
    env = detect_environment()
    tags = env.get("tags", [])

    # Evaluate each engram (optional with AI)
    for engram_id in shown_ids:
        engram = get_engram(engram_id)

        # AI evaluation (optional - requires API key)
        is_useful = evaluate_engram_usefulness(engram, session_data)
        # If no API key: is_useful = True (fail open)

        if is_useful:
            # Track match with tags
            update_match_stats(engram_id, repo=env.get("repo"), tags=tags)

    clear_shown()
```

**No API Key Required**: System defaults to marking all shown engrams as useful when API key unavailable.

---

## Database Schema

### Tables

#### `engrams`

```sql
CREATE TABLE engrams (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    level1 TEXT,  -- Parsed from category
    level2 TEXT,
    level3 TEXT,
    source TEXT DEFAULT 'manual',  -- 'auto-extracted' | 'manual' | 'feedback'
    source_sessions TEXT DEFAULT '[]',  -- JSON array of session IDs
    occurrence_count INTEGER DEFAULT 1,
    times_matched INTEGER DEFAULT 0,  -- Global match counter
    last_matched TEXT,
    created_at TEXT,
    updated_at TEXT,
    deprecated INTEGER DEFAULT 0,
    prerequisites TEXT DEFAULT NULL,  -- JSON: {repos, os, tags, paths, mcp_servers}
    pinned INTEGER DEFAULT 0  -- Auto-pinned or manually pinned
);
```

#### `engram_repo_stats` (Existing)

```sql
CREATE TABLE engram_repo_stats (
    engram_id INTEGER NOT NULL,
    repo TEXT NOT NULL,
    times_matched INTEGER DEFAULT 0,
    last_matched TEXT,
    PRIMARY KEY (engram_id, repo)
);
```

#### `engram_tag_stats` (NEW)

```sql
CREATE TABLE engram_tag_stats (
    engram_id INTEGER NOT NULL,
    tag_set TEXT NOT NULL,  -- JSON array: '["frontend", "react", "acme"]'
    times_matched INTEGER DEFAULT 0,
    last_matched TEXT,
    PRIMARY KEY (engram_id, tag_set)
);
```

#### `engram_tag_relevance`

```sql
CREATE TABLE engram_tag_relevance (
    engram_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    score REAL DEFAULT 0.0,           -- EMA-smoothed relevance score
    positive_evals INTEGER DEFAULT 0, -- times judged relevant with this tag
    negative_evals INTEGER DEFAULT 0, -- times judged irrelevant with this tag
    last_evaluated TEXT,
    PRIMARY KEY (engram_id, tag)
);
```

#### `session_audit`

```sql
CREATE TABLE session_audit (
    session_id TEXT PRIMARY KEY,
    shown_engram_ids TEXT NOT NULL,    -- JSON array
    env_tags TEXT NOT NULL,            -- JSON array
    repo TEXT,
    timestamp TEXT NOT NULL,
    transcript_path TEXT DEFAULT NULL
);
```

#### `processed_relevance_sessions`

```sql
CREATE TABLE processed_relevance_sessions (
    session_id TEXT PRIMARY KEY,
    processed_at TEXT,
    retry_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending'      -- 'pending' | 'completed' | 'failed'
);
```

#### `categories`

```sql
CREATE TABLE categories (
    path TEXT PRIMARY KEY,  -- e.g., 'development/frontend'
    description TEXT
);
```

#### `engram_categories` (Junction Table)

```sql
CREATE TABLE engram_categories (
    engram_id INTEGER NOT NULL,
    category_path TEXT NOT NULL,
    PRIMARY KEY (engram_id, category_path),
    FOREIGN KEY (engram_id) REFERENCES engrams(id)
);
```

### Indexes

```sql
CREATE INDEX idx_engrams_category ON engrams(category);
CREATE INDEX idx_engrams_level1 ON engrams(level1);
CREATE INDEX idx_engrams_deprecated ON engrams(deprecated);
```

---

## MCP Integration

### Server Configuration

```json
{
  "mcpServers": {
    "engrammar": {
      "command": "/Users/user/.engrammar/venv/bin/python",
      "args": ["/Users/user/.engrammar/engrammar/mcp_server.py"],
      "env": {
        "ENGRAMMAR_HOME": "/Users/user/.engrammar"
      }
    }
  }
}
```

### Available Tools

#### `engrammar_search`

```python
@mcp.tool()
def engrammar_search(
    query: str,
    category: str | None = None,
    tags: list[str] | None = None,  # NEW
    top_k: int = 5
) -> str
```

#### `engrammar_add`

```python
@mcp.tool()
def engrammar_add(
    text: str,
    category: str = "general",
    tags: list[str] | None = None,  # NEW
    prerequisites: dict | str | None = None,
    source: str = "manual"
) -> str
```

#### `engrammar_feedback`

```python
@mcp.tool()
def engrammar_feedback(
    engram_id: int,
    applicable: bool,
    reason: str = "",
    add_prerequisites: dict | str | None = None
) -> str
```

#### `engrammar_update`

```python
@mcp.tool()
def engrammar_update(
    engram_id: int,
    text: str | None = None,
    category: str | None = None,
    prerequisites: dict | str | None = None
) -> str
```

#### `engrammar_pin` / `engrammar_unpin`

```python
@mcp.tool()
def engrammar_pin(engram_id: int, prerequisites: dict | str | None = None) -> str

@mcp.tool()
def engrammar_unpin(engram_id: int) -> str
```

#### `engrammar_list`

```python
@mcp.tool()
def engrammar_list(
    category: str | None = None,
    include_deprecated: bool = False,
    limit: int = 20,
    offset: int = 0
) -> str
```

#### `engrammar_status`

```python
@mcp.tool()
def engrammar_status() -> str
# Shows: engram count, categories, index health, environment (including tags)
```

---

## Performance

### Benchmarks

| Operation            | Time   | Details                        |
| -------------------- | ------ | ------------------------------ |
| Tag detection        | <30ms  | 5 sources, ~1000 files scanned |
| Tag subset algorithm | <20ms  | Powerset generation + counting |
| Vector embedding     | ~50ms  | API call to Anthropic          |
| Search (hybrid)      | ~100ms | Vector + BM25 + RRF            |
| Tag filtering        | <5ms   | Set intersection operations    |
| Session start hook   | ~100ms | Load + filter pinned engrams   |
| Database write       | <10ms  | WAL mode, concurrent-safe      |

### Optimizations

**Tag Detection**:

- Cached git remote lookups (subprocess)
- Lazy file reading (only when markers exist)
- Set operations for deduplication

**Search**:

- Numpy for vector operations
- RRF instead of score normalization (faster)
- Tag relevance filtering after RRF (post-ranking, not pre-filtering)

**Auto-Pin**:

- Powerset limited to size 4 (prevents combinatorial explosion)
- Minimal subset pruning (avoids redundant checks)
- Only runs when tags present

**Database**:

- WAL mode for concurrent reads
- Indexes on common query patterns
- JSON for flexible prerequisites (no schema migrations)

### Memory Usage

| Component                       | Size       |
| ------------------------------- | ---------- |
| Embeddings index (1000 engrams) | ~2MB       |
| Engram metadata                 | ~500KB     |
| Tag stats (10 tag sets/engram)  | ~50KB      |
| BM25 index                      | ~1MB       |
| **Total**                       | **~3.5MB** |

---

## Extraction Pipeline

### Overview

Engrams are automatically extracted from Claude Code conversation transcripts stored as JSONL files in `~/.claude/projects/`. The extractor sends conversation content to Haiku for analysis, looking specifically for **friction moments** — not task summaries.

### Transcript Format

Each JSONL file contains one JSON object per line with these entry types:

| Entry Type | Contains | Used by Extractor? |
|---|---|---|
| `file-history-snapshot` | File backup metadata | No |
| `progress` | Hook events, agent progress | No |
| `user` | User messages (text + tool results) | Yes — `message.content` text parts |
| `assistant` | Model responses (text + thinking + tool_use) | Yes — `message.content` text parts |

### What Gets Sent to Haiku

The extractor (`_read_transcript_messages`) reads the JSONL and:

1. **Filters** to only `user` and `assistant` message types
2. **Extracts text** from `message.content` (handles both string and array formats)
3. **Strips injected engrammar blocks** (`[ENGRAMMAR_V1]...[/ENGRAMMAR_V1]`) to avoid re-learning previously injected engrams
4. **Truncates** each message to 500 chars
5. **Caps total** at 8000 chars (keeps the last 8000)

The result is a compressed conversation like:
```
user: let's work on TAPS-2126
assistant: Here's the ticket: TAPS-2126 - Remove pact. Let me explore...
user: don't just plan, actually make the changes
assistant: You're right. Let me start implementing...
```

### Extraction Criteria

The prompt instructs Haiku to **only** extract from friction patterns:

1. **User corrections** — assistant tried A, user said "no, do B"
2. **Repeated struggle** — multiple turns on something avoidable
3. **Discovered conventions** — user revealed a project rule
4. **Tooling gotchas** — unexpected tool/API behavior

The prompt explicitly rejects:
- User task instructions ("build X", "add Y")
- Summaries of what was built
- Generic programming advice
- Implementation details

### Dedup During Extraction

Each extracted engram is checked against existing engrams via `find_similar_engram()`:
- **Embedding similarity** (threshold 0.85) using the Voyage index
- **Fallback**: word overlap (threshold 0.70)

The embedding index is **rebuilt after each transcript** so subsequent transcripts dedup against all previously extracted engrams in the same run.

### Per-Transcript Pipeline

```
For each transcript (oldest-first):
    1. Read metadata → extract cwd, repo
    2. Detect env tags by chdir to transcript's cwd
    3. Write session_audit record (for tag enrichment)
    4. Read existing instructions (CLAUDE.md, AGENTS.md) to avoid duplicating documented knowledge
    5. Send transcript text + instructions to Haiku
    6. Parse JSON array response (robust parser handles markdown fences, extra text)
    7. For each extracted engram:
       a. Infer prerequisites from text + project signals
       b. Enrich with session env tags
       c. Check dedup → merge into existing or add new
       d. Initialize tag relevance scores from env tags
    8. Mark session as processed
    9. Rebuild embedding index (for next transcript's dedup)
```

### Post-Extraction

After all transcripts:
- **Backfill shown_engram_ids** in session_audit records by searching user prompts against the engram DB
- This prepares data for the evaluation pipeline

### CLI Usage

```bash
# Extract from oldest N transcripts
engrammar extract --limit 20

# Dry run (show what would be extracted)
engrammar extract --limit 5 --dry-run
```

### Automatic Extraction

The SessionEnd hook triggers background evaluation for the current session:
```python
subprocess.Popen([cli_path, "evaluate", "--session", session_id], ...)
```

---

## Data Flow

### Engram Lifecycle

```
1. Creation
   Transcript JSONL → extractor → Haiku analysis → add_engram() → DB
   OR: User → CLI/MCP → add_engram() → DB

2. Indexing
   DB → build_index() → Embeddings → .npy file

3. Matching
   SessionStart/PreToolUse → search() → RRF → tag relevance filter/boost → results

4. Tracking
   SessionEnd → record audit → evaluator → tag relevance scores (EMA)

5. Auto-Pin
   update_match_stats() → find_auto_pin_tag_subsets() → threshold reached → UPDATE pinned=1
   OR: tag relevance avg > 0.6 with enough evidence → auto-pin

6. Filtering (next session)
   search() → tag relevance scores filter strong negatives, boost positives
```

### Tag Flow

```
Session Start
    ↓
detect_environment()
    ↓
detect_tags() ← Path, Git, Files, Deps, Structure
    ↓
Environment: {os, repo, cwd, mcp_servers, tags: [...]}
    ↓
Hook: PreToolUse
    ↓
search(query) → RRF → tag relevance filter/boost → results
    ↓
Show relevant engrams + record in session_shown_engrams
    ↓
Session End
    ↓
Write session_audit (shown engrams + env tags + transcript path)
    ↓
Evaluator (async, via daemon)
    ↓
Haiku judges relevance per engram → raw scores
    ↓
update_tag_relevance(engram_id, tag_scores) → EMA update per tag
    ↓
Next Session: Scores filter irrelevant engrams, boost relevant ones
```

---

## Backward Compatibility

### No Breaking Changes

All changes are additive:

- ✅ Existing engrams work without tags
- ✅ Repo-based auto-pin continues to work
- ✅ Existing hooks unchanged (just pass extra params)
- ✅ Search works without tag filter
- ✅ Prerequisites remain optional

### Migration Path

**No migration required**. System adapts:

1. Existing engrams have `prerequisites=NULL` → match in all environments
2. New matches start tracking tags → gradual tag_stats population
3. Auto-pin can trigger on repo OR tags → dual system
4. Users can manually add tags to existing engrams

---

## Security Considerations

### API Keys

**No API key required for core functionality**:

- Tag detection: filesystem/git only
- Search: local embeddings + BM25
- Auto-pin: local algorithm
- Session end: defaults to fail-open (marks all as useful)

**Optional AI evaluation**:

- Session end hook can evaluate engram usefulness with Haiku
- Requires `ANTHROPIC_API_KEY` or `~/.claude.json`
- Gracefully falls back to simple tracking without AI

### File Access

- Only reads files in current working directory
- Git operations are read-only
- No writes outside `~/.engrammar/`

### SQL Injection

- All queries use parameterized statements
- JSON fields validated before parsing
- No user input concatenated into SQL

---

## Future Enhancements

### Planned Features

1. **Tag Aliases**: Map related tags (`react` ↔ `reactjs`)
2. **Tag Hierarchies**: `frontend/react/hooks` structure
3. **Multi-Environment Testing**: Test across multiple project types
4. **Web Dashboard**: Visualize engram networks and tag relationships

### Considered But Deferred

- **Automatic tag extraction from engram text**: Too brittle, prefer explicit
- **Tag suggestions**: Requires ML model, keep simple for now
- **Tag-based grouping in search**: Wait for user feedback
- **Custom tag patterns per user**: Config complexity vs. benefit

---

## Testing

### Test Coverage

```
tests/
├── test_tag_detection.py     # tag detection - path, git, files, deps, structure
├── test_tag_filtering.py     # prerequisites, structural prereqs, tag relevance filtering
├── test_tag_relevance.py     # EMA math, clamping, evidence function, auto-pin/unpin
├── test_tag_stats.py         # database tracking, tag subset algorithm, auto-pin
├── test_search.py            # RRF fusion, search filtering, edge cases
├── test_prerequisites.py     # structural prerequisite checking
├── test_evaluator.py         # evaluation pipeline, retry behavior
├── test_session_audit.py     # audit recording, pending evaluations
└── test_session_end.py       # hook integration
```

### Running Tests

```bash
# All tests
~/.engrammar/venv/bin/python -m pytest tests/ -v

# Specific test file
pytest tests/test_tag_detection.py -v

# With coverage
pytest tests/ --cov=engrammar --cov-report=html
```

### Manual Testing

```bash
# Tag detection
cd ~/work/acme/app-repo
~/.engrammar/engrammar-cli detect-tags

# Auto-pin simulation
python3 tests/manual_auto_pin_test.py

# End-to-end search
python3 tests/manual_search_test.py
```

---

## Troubleshooting

### Tag Detection Issues

**Problem**: Tags not detected

- Check `detect-tags` output
- Verify file markers exist (tsconfig.json, package.json)
- Check git remote: `git remote -v`

**Problem**: Wrong tags detected

- Review `tag_patterns.py` patterns
- Add custom patterns if needed
- Use `--tags` parameter to override

### Auto-Pin Not Triggering

**Problem**: Engram not auto-pinning

- Check tag_stats: `SELECT * FROM engram_tag_stats WHERE engram_id = X`
- Verify 15 match threshold reached
- Ensure common tags exist across tag sets

### Search Issues

**Problem**: Engrams not appearing

- Check prerequisites match: `engrammar_status` (shows env tags)
- Verify engram not deprecated
- Rebuild index: `engrammar rebuild`

---

## Glossary

| Term             | Definition                                                         |
| ---------------- | ------------------------------------------------------------------ |
| **Tag**          | Environment identifier (e.g., 'frontend', 'acme', 'react')         |
| **Tag Set**      | Sorted list of tags for an environment                             |
| **Tag Subset**   | Smaller set contained within multiple tag sets                     |
| **Auto-Pin**     | Automatic marking of engrams as always-show when threshold reached |
| **Prerequisite** | Condition for showing a engram (repo, os, tags, etc.)              |
| **RRF**          | Reciprocal Rank Fusion - algorithm for merging ranked lists        |
| **BM25**         | Best Matching 25 - probabilistic relevance ranking                 |
| **MCP**          | Model Context Protocol - Claude's tool integration system          |
| **Hook**         | Event-triggered code injection point                               |
| **Fail-open**    | Default to permissive behavior on error                            |

---

## References

- [BM25 Algorithm](https://en.wikipedia.org/wiki/Okapi_BM25)
- [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- [Anthropic Embeddings](https://docs.anthropic.com/en/docs/embeddings)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
