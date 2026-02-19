# Issue #31: Session-End Tests Can Spawn Real CLI Jobs

- Severity: Medium
- Complexity: C1 (Low complexity, low-hanging)
- Status: Open

## Problem
`hooks/on_session_end.py` now starts `engrammar-cli evaluate --session ...` via `subprocess.Popen`, but hook tests do not mock that subprocess call.

## Why It Matters
Unit tests can trigger real background jobs in developer environments (or fail differently in CI without installed CLI), introducing test side effects and flakiness.

## Suggested High-Level Solution
1. Mock `subprocess.Popen` in session-end hook tests.
2. Assert launch arguments explicitly in tests.
3. Optionally guard launch behind config/env flag for testability.
4. Add one integration test that verifies evaluator trigger behavior with controlled subprocess stubbing.
