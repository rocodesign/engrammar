# Engrammar

A semantic knowledge system that learns from Claude Code sessions and injects relevant lessons per-prompt. Replaces flat `lessons-learned.md` files with hybrid search (vector + BM25) that surfaces the right knowledge at the right time.

**Engram** (memory trace) + **Grammar** (learned rules) = workflow knowledge encoded as searchable lessons.

## How it works

Engrammar runs as three Claude Code hooks + an MCP server:

1. **SessionStart** — injects pinned lessons matching the current environment (repo, OS, path) and starts the search daemon in the background
2. **UserPromptSubmit** — searches lessons relevant to each prompt (~40ms via daemon)
3. **PreToolUse** — searches lessons relevant to each tool call (file paths, commands)
4. **MCP Server** — gives Claude direct access to add, search, update, and deprecate lessons

A background daemon keeps the embedding model warm for 15 minutes, bringing hook latency from ~300ms (cold start) to ~40ms (warm).

## Architecture

```
~/.engrammar/
├── engrammar/               # Python package
│   ├── config.py            # Settings loader + paths
│   ├── db.py                # SQLite CRUD + migrations
│   ├── embeddings.py        # FastEmbed wrapper + numpy index
│   ├── search.py            # Hybrid search (vector + BM25 + RRF)
│   ├── environment.py       # OS/repo/path/MCP detection
│   ├── daemon.py            # Background search daemon (Unix socket)
│   ├── client.py            # Daemon client (used by hooks)
│   ├── mcp_server.py        # MCP server (FastMCP over stdio)
│   └── register_hooks.py    # Hook + MCP registration
├── hooks/
│   ├── on_session_start.py  # SessionStart hook
│   ├── on_prompt.py         # UserPromptSubmit hook
│   └── on_tool_use.py       # PreToolUse hook
├── venv/                    # Python 3.10+ virtual environment
├── cli.py                   # CLI tool
├── lessons.db               # SQLite database
├── embeddings.npy           # Vector index (memory-mapped)
├── embedding_ids.npy        # Lesson ID mapping
├── config.json              # User configuration
├── .daemon.sock             # Unix socket (when daemon is running)
├── .daemon.pid              # Daemon PID file
├── .daemon.log              # Daemon log
├── .session-shown.json      # Dedup tracking (cleared per session)
└── .last-search.json        # Last search results (debug)
```

## Installation

```bash
git clone https://github.com/user/engrammar.git
cd engrammar
bash setup.sh
```

Requires Python 3.10+ (for MCP SDK). The setup script will:
- Find the best available Python (3.13 → 3.12 → 3.11 → 3.10)
- Create a venv at `~/.engrammar/venv/`
- Install dependencies (fastembed, numpy, rank_bm25, mcp)
- Copy source to `~/.engrammar/`
- Initialize the database and import existing lessons
- Build the embedding index
- Register hooks in `~/.claude/settings.json`
- Register the MCP server in `~/.claude.json` with `defer_initialization: false`
- Auto-allow engrammar MCP tools in permissions

After setup, restart Claude Code to activate the hooks and MCP server.

### Why `defer_initialization: false`?

By default, MCP tools are deferred (loaded on-demand via ToolSearch). Engrammar tools are set to load immediately because:
- They're core system infrastructure for learning and knowledge management
- Deferring them requires Claude to call ToolSearch twice (once without prefix, once with `mcp__engrammar__` prefix)
- Loading them immediately (~100ms) is acceptable for 10 tools
- Makes tools available instantly without discovery friction

If you need to re-enable deferring (e.g., for performance with many MCP servers), remove the `defer_initialization` line from `~/.claude.json`.

## Search

Engrammar uses **hybrid search** combining two approaches with Reciprocal Rank Fusion:

| Method | Strength | Example |
|--------|----------|---------|
| **Vector** (FastEmbed, BAAI/bge-small-en-v1.5) | Semantic similarity | "fix component layout" matches "Never use inline styles" |
| **BM25** (rank_bm25) | Exact keyword match | "figma" matches lessons about Figma MCP tools |

Results are filtered by **environment prerequisites** — lessons can be scoped to specific repos, OS, directory paths, or MCP server availability.

### Performance (11 lessons, Apple Silicon)

| Component | Latency |
|-----------|---------|
| Session start hook | 38ms |
| Prompt hook (daemon warm) | 40ms |
| Tool hook (daemon warm) | 40ms |
| Raw daemon search (socket) | 20ms |
| Embedding model cold load | 208ms (once, at daemon start) |

## Daemon

The search daemon starts lazily on the first hook call and keeps the FastEmbed model warm in memory. This avoids the ~200ms model load on every hook invocation.

- **Starts**: automatically on first hook call (or session start)
- **Stops**: after 15 minutes of inactivity
- **Socket**: `~/.engrammar/.daemon.sock` (Unix domain socket)
- **Fallback**: if daemon is unavailable, hooks fall back to direct search (~300ms)

## MCP Tools

When the MCP server is connected, Claude has access to these tools:

| Tool | Description |
|------|-------------|
| `engrammar_search` | Search lessons by semantic similarity + keywords |
| `engrammar_add` | Add a new lesson |
| `engrammar_update` | Update lesson text, category, or prerequisites |
| `engrammar_deprecate` | Soft-delete a lesson |
| `engrammar_feedback` | Report whether a surfaced lesson was applicable |
| `engrammar_categorize` | Add/remove categories (lessons can have multiple) |
| `engrammar_pin` | Pin a lesson (always injected at session start) |
| `engrammar_unpin` | Unpin a lesson |
| `engrammar_list` | List all lessons with pagination |
| `engrammar_status` | System status — lesson count, categories, index health |

## CLI

```bash
PYTHON=~/.engrammar/venv/bin/python
CLI=~/.engrammar/cli.py

$PYTHON $CLI status                          # DB stats, index health
$PYTHON $CLI search "inline styles"          # Search lessons
$PYTHON $CLI add "lesson text" --category dev/frontend  # Add a lesson
$PYTHON $CLI import lessons.json             # Import from JSON
$PYTHON $CLI export                          # Export to markdown
$PYTHON $CLI rebuild                         # Rebuild embedding index
```

## Configuration

Edit `~/.engrammar/config.json`:

```json
{
  "search": {
    "top_k": 3
  },
  "hooks": {
    "prompt_enabled": true,
    "tool_use_enabled": true,
    "skip_tools": ["Read", "Glob", "Grep", "WebFetch", "WebSearch"]
  },
  "display": {
    "max_lessons_per_prompt": 3,
    "max_lessons_per_tool": 2,
    "show_categories": true
  }
}
```

## Prerequisites (Environment Filtering)

Lessons can have JSON prerequisites that scope them to specific environments:

```json
{
  "repos": ["app-repo"],
  "os": ["darwin"],
  "paths": ["~/work/acme"],
  "mcp_servers": ["figma"]
}
```

A lesson only surfaces when **all** specified prerequisites match the current environment. Lessons without prerequisites are always eligible.

## Auto-Pin

When a lesson is matched 15+ times in a specific repo, it's automatically pinned with that repo as a prerequisite. Pinned lessons are injected at every session start (when prerequisites match), regardless of search relevance.

## Database Schema

```sql
-- Core lesson storage
CREATE TABLE lessons (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    level1 TEXT, level2 TEXT, level3 TEXT,  -- parsed from category path
    source TEXT,                             -- "auto-extracted" | "manual" | "feedback"
    prerequisites TEXT,                      -- JSON: {repos, os, paths, mcp_servers}
    pinned INTEGER DEFAULT 0,
    occurrence_count INTEGER DEFAULT 1,
    times_matched INTEGER DEFAULT 0,
    last_matched TEXT,
    deprecated INTEGER DEFAULT 0,
    created_at TEXT, updated_at TEXT
);

-- Multiple categories per lesson
CREATE TABLE lesson_categories (
    lesson_id INTEGER,
    category_path TEXT,
    PRIMARY KEY (lesson_id, category_path)
);

-- Per-repo match tracking (for auto-pin)
CREATE TABLE lesson_repo_stats (
    lesson_id INTEGER,
    repo TEXT,
    match_count INTEGER DEFAULT 0,
    last_matched TEXT,
    PRIMARY KEY (lesson_id, repo)
);
```

## Development

Source lives at `~/work/ai-tools/engrammar/`. After making changes:

```bash
bash setup.sh  # Redeploys to ~/.engrammar/
```

The setup script preserves `config.json` and `lessons.db` on redeploy.
