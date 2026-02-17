# Resolved: Issues #1-#4 Tag-Relevance Redesign

- Severity: Resolved
- Status: Closed

## Summary
Issues #1-#4 were resolved together by replacing the old usefulness flow with per-tag relevance scoring and an audit-driven evaluator pipeline.

## Design (Implemented)

Problem: SessionEnd usefulness evaluation had little context, could fail-open, and reinforced a positive-only loop.

Solution:
1. In-session feedback: Hook output uses `[ENGRAMMAR_V1]` with `EG#ID` markers.
2. SessionEnd audit: Store deterministic record of shown lesson IDs and context.
3. SessionStart async evaluation: Process audit records through `claude -p` (Haiku) for per-tag scores.

## Key Implemented Pieces
- Structured hook output with stable lesson IDs.
- MCP instruction path for `engrammar_feedback` on non-applicable lessons.
- DB tables: `lesson_tag_relevance`, `session_audit`, `processed_relevance_sessions`.
- EMA-based tag relevance scoring with clamping and thresholds.
- Search integration via normalized tag relevance boost.
- Auto-pin/unpin based on score + evidence rules.
- Removal of old evaluation/dependency paths.

## Closed Issues
- #1 Usefulness evaluation unreliable by design.
- #2 Fail-open pattern defeated intelligent matching.
- #3 Auto-pin positive-only loop.
- #4 Inconsistent fail-open vs fail-closed paths.
