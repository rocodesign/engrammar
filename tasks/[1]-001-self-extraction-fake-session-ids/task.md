# Task: Fix Self-Extraction Fake Session IDs

- Priority: High
- Complexity: C1 (low-hanging)
- Related issue: `issues/open/[2]-031-self-extraction-fake-session-ids/issue.md`
- Status: Open

## Problem

MCP `engrammar_add` stores placeholder strings ("current-sess", "conversation", "engrammar-pl") instead of real Claude session IDs. ~20 lessons have fake IDs, ~10 have empty `source_sessions`.

This breaks tag enrichment (`get_env_tags_for_sessions` can't look up audit records), dedup merging across sessions, and traceability.

## Fix

1. **MCP instructions prompt**: Pass real `session_id` from hook context into the instructions block so the model has it available when calling `engrammar_add`.
2. **Handler validation**: In `engrammar_add` handler, validate that `source_sessions` entries look like real UUIDs (36-char hex pattern). Warn on obvious placeholders.
3. **Hook plumbing**: `SessionStart` hook already receives `session_id` in stdin JSON. Thread it through to the MCP instructions block.
4. **Backfill migration**: Match fake-ID lessons to real sessions by timestamp proximity (`lesson.created_at` vs `session_audit.timestamp`).

## Files

- `src/mcp_server.py` — handler validation
- MCP instructions prompt (in hook or config)
- `hooks/on_session_start.py` — pass session_id into instructions
