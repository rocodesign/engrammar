# Task: Fix Extraction Prompt Wrong Categories

- Priority: Medium
- Complexity: C1 (low-hanging)
- Related issue: `issues/open/[3]-030-wrong-categories-from-extraction/issue.md`
- Status: Open

## Problem

Haiku defaults to "figma" as catch-all topic. Lessons about cli.py, Serena, facets, prerequisites all get `tools/figma` category. 10+ lessons miscategorized.

## Fix

1. **Expand topic examples** in `TRANSCRIPT_EXTRACTION_PROMPT` and `EXTRACTION_PROMPT` to cover: `engrammar`, `testing`, `architecture`, `tooling`, `workflow`, `configuration`, `session-management`.
2. **Add explicit instruction**: "Use 'general' if no specific topic fits. Never force a topic that doesn't match the lesson content."
3. **Expand `TOPIC_CATEGORY_MAP`** with entries for common misses so even vague topics map to reasonable categories.
4. **Optional post-extraction validation**: If Haiku's returned topic doesn't appear in the lesson text or any keyword map, remap to `general`.

## Files

- `src/extractor.py` — both prompts + `TOPIC_CATEGORY_MAP`
