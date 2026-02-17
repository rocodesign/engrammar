# Issue #9: CLI Argument Parsing Is Hand-Rolled

- Severity: Low
- Complexity: C2 (Medium complexity)
- Status: Open

## Problem
CLI commands parse `sys.argv` manually across many command functions.

## Why It Matters
Harder to maintain, validate, and extend consistently.

## Suggested High-Level Solution
1. Introduce `argparse` command-by-command (start with `update`, `search`, `add`).
2. Keep existing command names/flags for backward compatibility.
3. Add shared validation and consistent error messages.
4. Finish migration by removing manual loops.
