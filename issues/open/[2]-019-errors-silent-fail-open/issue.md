# Issue #19: Errors Are Mostly Silent (Fail-Open)

- Severity: High
- Complexity: C2 (Medium complexity)
- Status: Open

## Problem
Hooks intentionally fail-open and log to `.hook-errors.log`, but users get no direct signal when pipeline behavior degrades.

## Why It Matters
Production failures can go unnoticed for long periods.

## Suggested High-Level Solution
1. Keep fail-open behavior to avoid blocking Claude.
2. Add low-noise health surfaces:
   - `engrammar status` should include recent hook error counts.
   - Add last-error timestamp and short summary.
3. Optionally emit one non-blocking warning line per session when recent failures exist.
4. Add log rotation and error categorization.
