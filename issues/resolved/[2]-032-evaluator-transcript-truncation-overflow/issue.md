# Issue #32: Evaluator Transcript Truncation Exceeds Max Chars

- Severity: High
- Complexity: C1 (Low complexity, low-hanging)
- Status: Open

## Problem

`_read_transcript_file()` and `_find_transcript_excerpt()` enforce truncation using `head + marker + tail`, but they split by `max_chars // 2` without budgeting the marker length.

## Why It Matters

The returned transcript can exceed `max_chars`, violating the function contract and failing tests.

## Suggested High-Level Solution

1. Reserve space for the omission marker before slicing head/tail.
2. Guarantee `len(result) <= max_chars` for all values.
3. Share truncation logic in a helper used by both transcript readers.
4. Add a focused test for the marker-overhead edge case.
