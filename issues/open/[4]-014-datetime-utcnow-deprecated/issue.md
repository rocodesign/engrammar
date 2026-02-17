# Issue #14: `datetime.utcnow()` Deprecated Usage

- Severity: Low
- Complexity: C1 (Low complexity, low-hanging)
- Status: Open

## Problem
Several modules still use `datetime.utcnow()`.

## Why It Matters
Timezone-naive UTC timestamps are deprecated and less explicit.

## Suggested High-Level Solution
1. Replace with `datetime.now(timezone.utc)` everywhere.
2. Keep storage format ISO8601; include timezone offset.
3. Do this in one targeted refactor with test updates.
