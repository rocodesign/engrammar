# Issue #8: Config Cache In Long-Lived Daemon

- Severity: Medium
- Complexity: C1 (Low complexity, low-hanging)
- Status: Open

## Problem
`load_config()` caches once per process, and the daemon can run for many minutes.

## Why It Matters
Config edits are ignored until daemon restart.

## Suggested High-Level Solution
1. Add mtime-based config reload (`reload if CONFIG_PATH changed`).
2. Check reload on each request (cheap mtime check only).
3. Keep cache for non-daemon processes as-is.
4. Add a `daemon reload-config` request for explicit refresh.
