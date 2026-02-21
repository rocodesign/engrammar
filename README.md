# Engrammar

**Semantic Knowledge System for Claude Code**

Engrammar automatically learns from your Claude Code sessions and surfaces relevant engrams at the right time, making Claude more helpful with every interaction.

## Quick Start

```bash
# Initialize
~/.engrammar/engrammar-cli setup

# Check status
~/.engrammar/engrammar-cli status

# Detect environment tags
~/.engrammar/engrammar-cli detect-tags

# Search engrams
~/.engrammar/engrammar-cli search "component patterns"

# Add a engram
~/.engrammar/engrammar-cli add "Use Tailwind for UI components" --category dev/frontend --tags acme,react
```

## Features

### 🎯 Smart Tag-Based Filtering

Engrams automatically adapt to your environment:

- **Auto-detected tags**: Detects context from paths, git, files, dependencies
- **Cross-project learning**: Engrams valuable in `['acme', 'frontend']` can auto-pin to all `['frontend']` projects
- **Intelligent matching**: Only shows engrams relevant to your current stack

### 📍 Auto-Pin System

Engrams automatically become permanent when proven useful:

- **15-match threshold**: After 15 matches, engrams auto-pin to their environment
- **Tag subset algorithm**: Finds minimal common tags across matches
- **Smart prerequisites**: Auto-adds repo or tag requirements

### 🔍 Hybrid Search

Vector similarity + BM25 keyword matching with Reciprocal Rank Fusion for optimal results.

### 🔗 MCP Integration

Direct access from Claude Code:

- `engrammar_search` - Find relevant engrams
- `engrammar_add` - Record new learnings
- `engrammar_feedback` - Refine engram relevance
- `engrammar_status` - System health check

### 🎣 Session Hooks

Automatically surfaces engrams at the right moment:

- **PreToolUse**: Shows engrams before tool execution
- **SessionStart**: Displays pinned engrams
- **SessionEnd**: Tracks which engrams were actually useful (no API key required)

## Installation

Engrammar is designed to work with Claude Code. It requires:

- Python 3.12+
- Claude Code CLI

The system works completely **without API keys** - the AI evaluation in session end hooks is optional and fails open.

## CLI Commands

| Command                                    | Description                             |
| ------------------------------------------ | --------------------------------------- |
| `setup`                                    | Initialize database and build index     |
| `status`                                   | Show system stats and environment       |
| `detect-tags`                              | Show detected environment tags          |
| `search "query" [--tags tag1,tag2]`        | Search engrams with optional tag filter |
| `add "text" --category cat [--tags t1,t2]` | Add new engram                          |
| `list [--category cat] [--limit N]`        | List all engrams                        |
| `update ID --text "new"`                   | Update engram                           |
| `pin ID`                                   | Pin engram to always show               |
| `deprecate ID`                             | Mark engram as outdated                 |

## Environment Detection

Engrammar detects tags from 5 sources:

1. **Paths**: `~/work/acme/*` → `'acme'`
2. **Git remotes**: `github.com/acme` → `'github'`, `'acme'`
3. **File markers**: `tsconfig.json` → `'typescript'`
4. **Dependencies**: `package.json` with `react` → `'react'`, `'frontend'`
5. **Structure**: `packages/` directory → `'monorepo'`

Example: In `~/work/acme/app-repo`:

```
Tags: davinci, docker, frontend, github, jest, monorepo,
      nodejs, tailwind, react, testing, acme, typescript
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for comprehensive technical documentation.

## Examples

### Auto-Pin Scenario

```bash
# Engram matches 6 times in ['acme', 'frontend', 'typescript']
# Engram matches 5 times in ['acme', 'frontend', 'react']
# Engram matches 4 times in ['personal', 'frontend', 'typescript']
# → Total: 15 matches with 'frontend' tag
# → Auto-pins with {"tags": ["frontend"]}
# → Now shows in ALL frontend projects
```

### Manual Tagging

```bash
# Add engram for specific context
engrammar add "Follow acme's React patterns" \
  --category development/frontend \
  --tags acme,react,frontend

# Search within context
engrammar search "state management" --tags react
```

### MCP Usage

```python
# In Claude Code session
engrammar_add(
    text="Use Tailwind table components for all data tables",
    category="development/frontend/components",
    tags=["acme", "react", "tailwind"]
)

engrammar_search(query="table component", tags=["react"])
```

## Configuration

Located at `~/.engrammar/config.json`:

```json
{
  "hooks": {
    "prompt_enabled": true,
    "tool_use_enabled": true,
    "skip_tools": ["Read", "Glob"]
  },
  "search": {
    "top_k": 5
  },
  "display": {
    "max_engrams_per_tool": 2
  }
}
```

## Project Structure

```
~/.engrammar/
├── engrammar/           # Core package
│   ├── db.py           # SQLite + auto-pin logic
│   ├── embeddings.py   # Vector search
│   ├── environment.py  # Tag detection
│   ├── search.py       # Hybrid search
│   ├── tag_detectors.py # Tag detection algorithms
│   ├── tag_patterns.py  # Detection patterns
│   └── mcp_server.py   # MCP integration
├── hooks/              # Claude Code hooks
│   ├── on_session_start.py
│   ├── on_tool_use.py
│   └── on_session_end.py
├── cli.py              # CLI interface
├── tests/              # Test suite
└── docs/               # Documentation
```

## Performance

| Operation            | Time          | Memory     |
| -------------------- | ------------- | ---------- |
| Tag detection        | <30ms         | Negligible |
| Tag subset algorithm | <20ms         | ~50KB      |
| Search with tags     | +5ms overhead | Negligible |
| Session start        | <100ms        | ~1MB       |

## Development

```bash
# Run tests
~/.engrammar/venv/bin/python -m pytest tests/ -v

# Tag detection tests
pytest tests/test_tag_detection.py -v

# Filtering tests
pytest tests/test_tag_filtering.py -v

# Database tests
pytest tests/test_tag_stats.py -v
```

## License

MIT

## Contributing

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for technical details on the system design.
