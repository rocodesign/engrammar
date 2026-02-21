# Issue #30: JSON Array Parser Can Return Wrong Array Shape

- Severity: High
- Complexity: C1 (Low complexity, low-hanging)
- Status: Open

## Problem
`_parse_json_array()` returns the first bracketed JSON array it can decode, even when it is not the engram payload (for example `[1]` from prefix text like `Note [1] ...`).

## Why It Matters
Extraction paths assume each parsed item is a dict and call `.get(...)`; if parser returns `[1]` or similar, extraction crashes with `AttributeError` instead of failing gracefully.

## Suggested High-Level Solution
1. Validate parsed output shape (`list[dict]`) before returning.
2. Continue scanning for the next array candidate when a decoded array has invalid shape.
3. Fall back to `[]` on invalid structure, matching prior fail-safe behavior.
4. Add parser tests for prefix text containing bracketed references.
