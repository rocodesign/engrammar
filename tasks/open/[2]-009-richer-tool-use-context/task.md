# Task: Richer Tool-Use Context for PreToolUse Search

- Priority: Medium
- Complexity: C2
- Status: Open

## Problem

The PreToolUse hook only sees the tool name and basic parameters (file_path, command, pattern). This is too shallow for meaningful engram search — a query like `"Bash git"` or `"Edit /src/config.py"` lacks enough semantic signal, so the search returns whatever floats to the top regardless of relevance.

A minimum score threshold (added in #009-prereq) helps filter out the worst noise, but the root issue is that the search query itself doesn't carry enough context about what the user is actually doing.

## Fix

Pass richer context into the search query for tool calls:

1. **File content snippets** — for Edit/Write tools, include a snippet of the file being modified (e.g. first 10 lines, or the `old_string` being replaced) in the search query.
2. **Diff context** — for Bash commands that produce diffs or modify files, include relevant diff hunks.
3. **Recent conversation context** — the hook input may include surrounding conversation context that could be forwarded to search.
4. **Tool-specific extractors** — different tools carry different useful signals:
   - `Edit`: `old_string` + `new_string` are highly semantic
   - `Write`: `file_path` extension + first lines of `content`
   - `Bash`: full `command` string, not just first word
   - `NotebookEdit`: `new_source` content

## Files

- `src/search.py` — `search_for_tool_context()` query construction
- `hooks/on_tool_use.py` — hook input parsing
- `src/daemon.py` — daemon handler for `tool_context` requests
