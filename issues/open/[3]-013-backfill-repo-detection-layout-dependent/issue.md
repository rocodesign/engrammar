# Issue #13: Backfill Repo Detection Is Path-Layout Dependent

- Severity: Medium
- Complexity: C1 (Low complexity, low-hanging)
- Status: Open

## Problem
Backfill infers repo from `cwd` only when the path contains `/work/`.

## Why It Matters
Historical sessions outside that layout lose repo attribution.

## Suggested High-Level Solution
1. Parse repo from transcript metadata when available.
2. Fallback to robust path parsing (`basename`-style heuristics), not `/work/` only.
3. Store `repo = null` explicitly when unknown (avoid wrong guesses).
4. Add tests for multiple path layouts.
