# Task: Extract tags from user prompt for dynamic tag affinity

- Priority: High (highest)
- Complexity: C2
- Status: Open

## Problem

Environment tags are static per repo — they reflect the project structure (package.json, Gemfile, etc.) but not what the user is actually doing in that moment. A user asking "commit this change" in a Python repo gets tags `[python, github, source]` but no `git` signal, so git convention engrams don't get boosted. Conversely, a user asking about "cypress tests" in a repo without Cypress in package.json gets no `cypress`/`testing` tag affinity.

The tag affinity multiplier is the primary mechanism for ranking relevant engrams above irrelevant ones, but it's blind to the task at hand.

## Fix

Add prompt-derived tags to the effective tag set used for affinity scoring in the UserPromptSubmit hook path:

1. **Keyword → tag mapping** — a lightweight dictionary matching prompt tokens to tags. No LLM call needed. Examples:
   - "commit", "push", "rebase" → `["git"]`
   - "cypress" → `["cypress", "testing"]`
   - "jest", "vitest" → `["testing"]`
   - "graphql", "mutation", "query" → `["graphql"]`
   - "apollo" → `["graphql", "apollo"]`
   - "react", "component", "hooks", "useState" → `["react", "frontend"]`
   - "docker", "container" → `["docker"]`
   - "deploy" → `["deployment"]`

2. **Merge with env tags** — `effective_tags = env_tags + prompt_tags`, used for the tag affinity embedding in `search()`. The env tags remain the baseline; prompt tags augment them per-query.

3. **Pass effective tags through the search path** — the `on_prompt.py` hook extracts prompt tags and passes them to search (via daemon or direct). The search function uses them for the tag affinity embedding instead of bare env tags.

4. **Keep mappings specific** — avoid broad mappings like "fix" → `["testing"]` that would boost unrelated engrams. Only map terms that strongly signal a specific domain.

## Considerations

- Prompt tags should NOT be used for the tag relevance filter (section 3.5 in engine.py) — that should stay on stable env tags only, since relevance scoring is accumulated over sessions
- Prompt tags should NOT be used for `enforce_prerequisites` — that's a hard structural gate, not a ranking signal
- The tag affinity embedding (section 3.1 in engine.py) is the right place — it's already a soft scoring mechanism
- Consider also applying prompt tags in the PreToolUse path via `_build_tool_query` context

## Files

- `src/search/tag_patterns.py` or new `src/search/prompt_tags.py` — keyword → tag mapping
- `src/search/engine.py` — accept optional `extra_tags` param for affinity scoring
- `hooks/on_prompt.py` — extract prompt tags and pass to search
- `src/infra/daemon.py` — forward prompt tags in search request

## Validation

- Search for "commit this change" from engrammar repo → git convention engrams should rank higher than without prompt tags
- Search for "write a cypress test" from a repo without cypress → cypress engrams should get affinity boost
- Search for "fix the rendering bug" → should NOT over-boost random testing engrams (keep mappings specific)
- Compare injection quality in a real session before/after
