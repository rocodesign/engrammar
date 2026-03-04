# Design: Reorganize src/ into subdirectories

**Date**: 2026-03-04
**Goal**: Improve navigability of the 18-file flat src/ directory by grouping into logical subdirectories.

## Structure

```
src/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── config.py            # configuration
│   ├── db.py                # database schema + queries
│   ├── embeddings.py        # vector index
│   └── prompt_loader.py     # prompt template loading
├── search/
│   ├── __init__.py
│   ├── engine.py            # search pipeline (renamed from search.py)
│   ├── environment.py       # environment/tag detection
│   ├── tag_detectors.py     # tag detection logic
│   └── tag_patterns.py      # regex patterns
├── pipeline/
│   ├── __init__.py
│   ├── extractor.py         # engram extraction
│   ├── evaluator.py         # relevance evaluation
│   └── dedup.py             # deduplication
└── infra/
    ├── __init__.py
    ├── daemon.py            # background daemon
    ├── client.py            # daemon client
    ├── hook_utils.py        # hook utilities
    ├── mcp_server.py        # MCP tool handlers
    └── register_hooks.py    # hook registration
```

## Grouping rationale

- **core/**: Foundation modules with no or minimal internal dependencies (config, db, embeddings, prompt_loader)
- **search/**: Search pipeline + environment detection chain (engine → environment → tag_detectors → tag_patterns)
- **pipeline/**: Batch processing — extraction, evaluation, deduplication (all depend on core/)
- **infra/**: Runtime infrastructure — daemon, client, MCP server, hook utilities, hook registration

## Import convention

All cross-subpackage imports use the full subpackage path:
```python
from engrammar.core.db import get_engram_count
from engrammar.search.engine import hybrid_search
from engrammar.pipeline.extractor import extract_engrams
```

## Rename

- `search.py` → `search/engine.py` to avoid `search.search` naming conflict

## Scope of changes

- ~50 import rewrites across: src/ modules, hooks/*.py, cli.py, backfill_stats.py, tests/
- Deploy script updated to copy subdirectories instead of flat `src/*.py`
- No backward-compatibility shims — clean rename (single-dev project, no external consumers)

## Dependency flow (enforced direction)

```
core/  ←  search/  ←  pipeline/
  ↑                      ↑
  └──────── infra/ ──────┘ (lazy imports in daemon/mcp_server)
```

hooks/ and cli.py can import from any subpackage.
