# Task: Extract Engrams at Session End

- Priority: High
- Complexity: C2 (medium)
- Status: Open

## Problem

After the initial batch extraction catches up on historical transcripts, ongoing engram learning relies on the model voluntarily calling `engrammar_add` via MCP instructions. This is unreliable — the model often doesn't do it, so friction and corrections go uncaptured.

The only fallback is manually re-running `engrammar extract`, which processes transcripts after the fact.

## Fix

Run extraction automatically at session end, alongside the existing evaluation.

The SessionEnd hook already spawns a background `engrammar-cli evaluate --session <uuid>`. Add a similar background call to extract engrams from the transcript that just finished.

### Considerations

1. **Dedup against MCP-added engrams**: If the model did call `engrammar_add` during the session, the session-end extraction must not create duplicates. The existing `find_similar_engram()` dedup should handle this.

2. **Single-transcript extraction**: Need a CLI path like `engrammar extract --session <uuid>` that processes one specific transcript, not a batch.

3. **Performance**: Haiku call takes 10-30s. This runs in a background process (`start_new_session=True`) so it doesn't block the user.

4. **Existing instructions filter**: The extraction already reads CLAUDE.md/AGENTS.md to avoid duplicating documented knowledge. This should work the same for single-session extraction.

5. **Index rebuild**: After extracting from one session, rebuild the embedding index so new engrams are immediately available for search in the next session.

## Files

- `hooks/on_session_end.py` — add background extraction call
- `cli.py` — add `extract --session <uuid>` support
- `src/extractor.py` — add single-session extraction function
