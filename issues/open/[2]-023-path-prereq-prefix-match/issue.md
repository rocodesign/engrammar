# Issue #23: Path Prerequisite Prefix False Matches

- Severity: High
- Complexity: C1 (Low complexity, low-hanging)
- Status: Open

## Problem
Path checks use string prefix matching (`cwd.startswith(path)`).

## Why It Matters
`/work/app` incorrectly matches `/work/application`.

## Suggested High-Level Solution
1. Normalize both paths (`expanduser`, `realpath`, trailing separator handling).
2. Use boundary-safe checks (`os.path.commonpath`/`pathlib`) instead of raw prefix.
3. Add tests for near-prefix collisions and symlinked paths.
