# Issue #5: `sys.path.insert(0, ENGRAMMAR_HOME)` Everywhere

- Severity: Low
- Complexity: C3 (High complexity)
- Status: Open

## Problem
Multiple entrypoints manually mutate `sys.path` to import `engrammar` modules.

## Why It Matters
This works, but it couples runtime behavior to filesystem layout and manual install steps.

## Suggested High-Level Solution
1. Package Engrammar as an installable Python project (`pyproject.toml`).
2. Use console entry points for CLI and hook scripts.
3. Keep `ENGRAMMAR_HOME` only for data/config paths, not import routing.
4. Remove `sys.path.insert(...)` once entry points are in place.
