# Engrammar

**Semantic Knowledge System for Claude Code**

Engrammar automatically learns from your Claude Code sessions and surfaces relevant engrams at the right time, making Claude more helpful with every interaction. It builds a persistent knowledge base of project conventions, debugging insights, tooling quirks, and workflow preferences — then injects the right ones into your sessions based on what you're doing and where you're doing it.

Unlike CLAUDE.md files which require manual curation, Engrammar extracts learnings from friction moments in past conversations (user corrections, repeated struggles, discovered conventions) and learns which contexts each engram belongs in through an automated evaluation pipeline.

## How It Works

1. **Hooks** inject relevant engrams into your Claude Code sessions at the right moment
2. **Search** combines vector similarity (fastembed) + BM25 keywords with Reciprocal Rank Fusion
3. **Environment detection** auto-detects project context from paths, git, files, dependencies
4. **Evaluation** learns which engrams are relevant in which contexts via per-tag relevance scoring
5. **Extraction** automatically discovers new engrams from session friction moments

## Features

### Smart Context Detection

Engrams automatically adapt to your environment. Tags are detected from paths, git remotes, file markers (tsconfig.json, package.json, Gemfile), dependencies, and directory structure. Cross-project learning means an engram proven useful in `['acme', 'frontend']` can auto-pin to all `['frontend']` projects.

### Hybrid Search with Tag Affinity

Vector similarity + BM25 keyword matching, merged with Reciprocal Rank Fusion. An environment tag affinity boost uses cosine similarity between your current environment tags and each engram's prerequisite tags to promote relevant results and demote irrelevant ones.

### Auto-Pin System

Engrams automatically become permanent when proven useful — after 15 matches across tag contexts, the system finds the minimal common tag subset and auto-pins. A separate tag-relevance auto-pin triggers when evaluator quality scores exceed thresholds.

### Evaluation Pipeline

After each session, an evaluator judges whether shown engrams were relevant, updating per-tag EMA scores. Strong negative scores filter engrams from future sessions in that context; positive scores boost ranking.

## MCP Tools

All 10 tools are available directly from Claude Code sessions:

| Tool | Description |
|------|-------------|
| `engrammar_search` | Semantic + keyword search with category and tag filters |
| `engrammar_add` | Add new engram with category, tags, and prerequisites |
| `engrammar_update` | Update engram text, category, or prerequisites |
| `engrammar_deprecate` | Soft-delete an outdated engram |
| `engrammar_feedback` | Record relevance feedback with optional per-tag scores |
| `engrammar_categorize` | Add/remove categories for multi-category engrams |
| `engrammar_pin` | Pin engram to always show at session start |
| `engrammar_unpin` | Unpin engram |
| `engrammar_list` | List engrams with category filter and pagination |
| `engrammar_status` | System health: engram count, categories, index, environment |

## Session Hooks

Four hooks automatically surface engrams at the right moment:

| Hook | Trigger | Purpose |
|------|---------|---------|
| **SessionStart** | Session begins | Inject pinned engrams, start daemon, run maintenance |
| **UserPromptSubmit** | User sends a prompt | Search engrams relevant to the prompt |
| **PreToolUse** | Before tool execution | Search engrams relevant to the tool being used |
| **Stop** | After each assistant response | Per-turn extraction + evaluation via daemon |

## CLI Commands

All 21 commands:

| Command | Description |
|---------|-------------|
| `setup` | Initialize database and build embedding index |
| `status` | Show DB stats, index health, environment, hook config |
| `detect-tags` | Show detected environment tags for current directory |
| `search` | Search engrams: `search "query" [--category CAT] [--tags t1,t2]` |
| `list` | List engrams: `list [--category CAT] [--limit N] [--verbose] [--sort id\|score\|matched]` |
| `log` | Show hook event log: `log [--tail N] [--session ID] [--hook HOOK]` |
| `add` | Add engram: `add "text" --category CAT [--tags t1,t2]` |
| `update` | Update engram: `update ID [--text "..."] [--category CAT] [--prereqs JSON]` |
| `deprecate` | Soft-delete engram: `deprecate ID` |
| `pin` | Pin engram for session start: `pin ID` |
| `unpin` | Unpin engram: `unpin ID` |
| `categorize` | Manage categories: `categorize ID add\|remove CATEGORY` |
| `import` | Import from file: `import FILE` |
| `export` | Export all engrams to markdown |
| `extract` | Extract engrams from transcripts: `extract [--limit N] [--session UUID] [--facets] [--dry-run]` |
| `rebuild` | Rebuild embedding index (content + tag embeddings) |
| `evaluate` | Run pending relevance evaluations: `evaluate [--limit N] [--session UUID]` |
| `backfill` | Create audit records from past sessions |
| `backfill-prereqs` | Retroactively set prerequisites on existing engrams |
| `reset-stats` | Reset all match counts and pins: `reset-stats --confirm` |
| `restore` | List DB backups and restore: `restore [--list] [N]` |

See [docs/CLI.md](docs/CLI.md) for full usage details.

## Getting Started

Requires Python 3.12+ and Claude Code CLI. No API keys needed — embeddings run locally via `fastembed`. The AI evaluation and extraction features use Haiku and are optional (fail open).

```bash
# Initialize database and build embedding index
engrammar setup

# Check system status and detected environment
engrammar status

# See what tags are detected for your current project
engrammar detect-tags

# Search your knowledge base
engrammar search "component patterns"

# Add a engram manually
engrammar add "Use Tailwind for UI components" --category dev/frontend --tags acme,react
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for comprehensive technical documentation including:

- Search pipeline (vector + BM25 + RRF + tag affinity boost + tag relevance filtering)
- Database schema (12 tables)
- Daemon system for fast hook search
- Auto-pin algorithm
- Extraction pipeline
- Evaluation and EMA scoring

## Development

```bash
# Run tests
~/.engrammar/venv/bin/python -m pytest tests/ -v

# Deploy changes to ~/.engrammar after editing
bash deploy.sh

# Deploy and restart daemon
bash deploy.sh --restart
```

## License

Apache 2.0 — see [LICENSE](LICENSE)
