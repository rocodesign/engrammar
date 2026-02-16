# Engrammar Documentation

Comprehensive documentation for the Engrammar semantic knowledge system.

## Documentation Index

### 📚 Getting Started

- **[README.md](../README.md)** - Overview, quick start, features
  - Installation & setup
  - Key features overview
  - Basic usage examples
  - Performance metrics

### 🎯 Quick Reference

- **[CHEATSHEET.md](CHEATSHEET.md)** - Quick command reference
  - All CLI commands with examples
  - MCP tool usage
  - Tag system quick reference
  - Common workflows
  - Troubleshooting tips

### 🏗️ Technical Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Comprehensive technical guide
  - System architecture
  - Core components deep dive
  - Tag detection pipeline
  - Auto-pin algorithm explained
  - Search architecture (Vector + BM25)
  - Hook system details
  - Database schema
  - MCP integration
  - Performance benchmarks
  - Data flow diagrams

- **[evaluation.md](evaluation.md)** - Evaluation & tag relevance scoring
  - How the evaluator pipeline works
  - EMA scoring math and convergence
  - Tag relevance filtering in search
  - Structural vs tag prerequisites
  - Debugging lesson visibility

## What Should I Read?

### I want to...

**...get started quickly**
→ [README.md](../README.md) + [CHEATSHEET.md](CHEATSHEET.md)

**...understand tag-based filtering**
→ [CHEATSHEET.md - Tag System](CHEATSHEET.md#tag-system)

**...learn common workflows**
→ [CHEATSHEET.md - Common Workflows](CHEATSHEET.md#common-workflows)

**...understand how auto-pin works**
→ [ARCHITECTURE.md - Auto-Pin Algorithm](ARCHITECTURE.md#auto-pin-algorithm)

**...see all CLI commands**
→ [CHEATSHEET.md - CLI Commands](CHEATSHEET.md#cli-commands)

**...use MCP tools**
→ [CHEATSHEET.md - MCP Tools](CHEATSHEET.md#mcp-tools)

**...understand how evaluation and tag scoring works**
→ [evaluation.md](evaluation.md)

**...understand the internals**
→ [ARCHITECTURE.md - Core Components](ARCHITECTURE.md#core-components)

**...debug issues**
→ [CHEATSHEET.md - Troubleshooting](CHEATSHEET.md#troubleshooting)

**...contribute or extend**
→ [ARCHITECTURE.md - Database Schema](ARCHITECTURE.md#database-schema)

## Quick Links

### Common Tasks

| Task | Reference |
|------|-----------|
| Add a lesson | [Cheatsheet - Add](CHEATSHEET.md#add-lessons) |
| Search lessons | [Cheatsheet - Search](CHEATSHEET.md#search) |
| Use tags | [Cheatsheet - Tag System](CHEATSHEET.md#tag-system) |
| Pin lessons | [Cheatsheet - Pin Management](CHEATSHEET.md#pin-management) |
| Understand auto-pin | [Architecture - Auto-Pin](ARCHITECTURE.md#auto-pin-algorithm) |

### Key Concepts

| Concept | Where to Learn |
|---------|----------------|
| Tags | [Cheatsheet - Tag System](CHEATSHEET.md#tag-system) |
| Prerequisites | [Cheatsheet - Prerequisites](CHEATSHEET.md#prerequisites) |
| Auto-Pin | [Architecture - Auto-Pin Algorithm](ARCHITECTURE.md#auto-pin-algorithm) |
| Search | [Architecture - Search Architecture](ARCHITECTURE.md#search-architecture) |
| Hooks | [Architecture - Hook System](ARCHITECTURE.md#hook-system) |
| Evaluation | [evaluation.md](evaluation.md) |
| Tag Relevance | [evaluation.md - Tag Relevance Scores](evaluation.md#tag-relevance-scores) |

## Feature Highlights

### 🏷️ Tag System

Automatically detects project context from:
- File paths (`~/work/acme/*` → `acme`)
- Git remotes (`github.com/acme` → `acme`, `github`)
- File markers (`tsconfig.json` → `typescript`)
- Dependencies (`package.json` with `react` → `react`, `frontend`)
- Directory structure (`packages/` → `monorepo`)

**See**: [Cheatsheet - Tag System](CHEATSHEET.md#tag-system)

### 🎯 Auto-Pin Algorithm

Learns which lessons are valuable across projects:
- Tracks matches per tag set
- Finds minimal common tags with 15+ matches
- Auto-pins to broader contexts

**Example**:
```
6 matches in ['acme', 'frontend', 'typescript']
5 matches in ['acme', 'frontend', 'react']
4 matches in ['personal', 'frontend', 'typescript']
→ Auto-pins to ['frontend'] (15 total)
```

**See**: [Architecture - Auto-Pin Algorithm](ARCHITECTURE.md#auto-pin-algorithm)

### 🔍 Hybrid Search

Combines vector similarity and BM25 keyword matching:
- **Vector**: Semantic understanding (Voyage embeddings)
- **BM25**: Keyword precision
- **RRF**: Reciprocal Rank Fusion merges results

**See**: [Architecture - Search Architecture](ARCHITECTURE.md#search-architecture)

### 🎣 Smart Hooks

Surfaces lessons at the perfect moment:
- **SessionStart**: Shows pinned lessons
- **PreToolUse**: Contextual suggestions before tool execution
- **SessionEnd**: Tracks usefulness (no API key required)

**See**: [Architecture - Hook System](ARCHITECTURE.md#hook-system)

## Example Workflows

### 1. Starting a New Feature

```bash
# Check environment
engrammar detect-tags

# Search for patterns
engrammar search "component patterns" --tags react

# Review suggestions before coding
```

### 2. After Fixing a Bug

```python
# Record the learning
engrammar_add(
    text="Always validate API responses before state updates",
    category="development/frontend/errors",
    tags=["react", "typescript", "api"]
)
```

### 3. Working Across Projects

```bash
# Lesson auto-detects context
cd ~/work/acme/app-repo
engrammar search "table component"  # Shows Acme-specific

cd ~/work/personal/my-app
engrammar search "table component"  # Shows generic frontend
```

## Configuration

Location: `~/.engrammar/config.json`

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
    "max_lessons_per_tool": 2
  }
}
```

## Files & Directories

```
~/.engrammar/
├── docs/
│   ├── README.md           # This file
│   ├── CHEATSHEET.md       # Quick reference
│   └── ARCHITECTURE.md     # Technical deep dive
├── engrammar/              # Core package
│   ├── db.py              # Database + auto-pin
│   ├── environment.py     # Tag detection
│   ├── search.py          # Hybrid search
│   ├── tag_detectors.py   # Tag algorithms
│   └── mcp_server.py      # MCP integration
├── hooks/                  # Session hooks
├── tests/                  # Test suite
├── lessons.db             # SQLite database
├── embeddings.npy         # Search index
└── config.json            # Configuration
```

## Support & Contribution

### Getting Help

1. Check [CHEATSHEET.md](CHEATSHEET.md) for common tasks
2. Review [ARCHITECTURE.md](ARCHITECTURE.md) for technical details
3. Search existing [GitHub Issues](https://github.com/anthropics/engrammar/issues)
4. Create new issue if needed

### Contributing

See [ARCHITECTURE.md](ARCHITECTURE.md) for:
- System architecture
- Database schema
- Component details
- Testing guidelines

## Version Information

- **Current Version**: 1.0 (Tag System)
- **Python**: 3.12+
- **Dependencies**: anthropic, numpy, rank-bm25
- **Database**: SQLite 3 (WAL mode)

## License

MIT

---

**Last Updated**: 2026-02-17

For the latest updates, see the [main README](../README.md).
