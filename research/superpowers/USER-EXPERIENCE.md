# Semantic Lesson Search: User Experience Design

## Guiding Principle

The lesson search system must be **invisible when working, diagnosable when not**.
The user should never have to think about embeddings, vectors, or indexes. They
should feel like Claude Code just "remembers" what it learned before.

---

## 1. What Happens When the Server Isn't Running?

### V1 Architecture: No Server, No Problem

The recommended V1 architecture (see ALTERNATIVES.md) has no server. The search runs
as an inline Python script called by the `UserPromptSubmit` hook. The only failure
modes are:

| Failure | What Happens | User Sees |
|---------|-------------|-----------|
| Python not installed | Hook returns exit code 1 | Nothing (Claude continues without lessons) |
| FastEmbed not installed | Import error, exit code 1 | Nothing (graceful degradation) |
| lessons.npy missing | Script skips vector search, falls back to BM25-only | Slightly worse lesson relevance |
| lessons.db missing | Script outputs empty result | No lessons injected |
| Script crashes | Exit code non-zero | Nothing (Claude continues normally) |

**Key design decision**: The hook must NEVER block Claude Code. Any error in the
lesson search script should fail silently. The `UserPromptSubmit` hook already
supports this -- a non-zero exit code means "continue without this hook's output."

### V2 Architecture: MCP Server Resilience

When the MCP server is added:
- If the MCP server is not running, Claude simply does not have the `search_lessons`
  tool available. No error, no warning.
- The `UserPromptSubmit` hook still runs independently, providing baseline lesson
  injection.
- The MCP server can auto-start with Claude Code sessions (stdio transport) or run
  as a persistent launchd service.

### Diagnostic Commands

For when the user wants to check system health:

```
You: /lessons status

Claude: Lesson search system status:
  Database: 847 lessons in ~/.claude/lessons/lessons.db
  Index: 847 embeddings in ~/.claude/lessons/lessons.npy (last rebuilt: 2 hours ago)
  Categories: 12 active categories
  Hook: UserPromptSubmit configured in ~/.claude/settings.json
  MCP: lesson-search server connected (V2 only)
  Last search: 23ms (3 results for "inline styles picasso")
```

This should be implemented as a Claude Code skill (`~/.claude/skills/lessons/`)
that reads status files and reports health.

---

## 2. How Does the User Add/Edit/Delete Lessons Manually?

### Adding Lessons

**Automatic (existing flow, enhanced)**:
The current `extract-lessons.py` script already extracts lessons from session facets.
This continues to work. The enhancement is that newly extracted lessons get embedded
and added to the index automatically.

**Manual via conversation**:
```
You: Remember this: never use `yarn test --watch` in CI, it hangs forever.
     Category: devops/ci-cd

Claude: [Calls add_lesson MCP tool or writes directly to lessons.db]
        Added lesson to devops/ci-cd:
        "Never use `yarn test --watch` in CI -- it hangs indefinitely.
         Use `yarn test --ci` or `yarn test --watchAll=false` instead."
        (Lesson #848)
```

**Manual via file edit**:
For bulk operations, expose a `lessons export` / `lessons import` flow:

```
You: /lessons export

Claude: Exported 847 lessons to ~/.claude/lessons/export.md
        Edit this file, then run /lessons import to re-index.
```

The export format should be human-readable markdown:

```markdown
## devops/ci-cd

- [#201] Never use `yarn test --watch` in CI -- it hangs indefinitely.
  Added: 2026-01-15 | Source: auto-extracted | Occurrences: 3

- [#202] GitHub Actions runners have 7GB RAM; large TypeScript projects
  need `--max-old-space-size=4096` in CI.
  Added: 2026-01-20 | Source: manual | Occurrences: 1
```

### Editing Lessons

**Via conversation (V2, MCP)**:
```
You: Edit lesson #201 to also mention that --forceExit is needed for Jest

Claude: [Calls edit_lesson MCP tool]
        Updated lesson #201:
        "Never use `yarn test --watch` in CI -- it hangs indefinitely.
         Use `yarn test --ci --forceExit` or `yarn test --watchAll=false
         --forceExit` instead."
```

**Via direct file edit (V1)**:
Lessons live in SQLite. Provide a simple CLI:
```bash
python3 ~/.claude/lessons/manage.py edit 201
# Opens $EDITOR with the lesson text
```

### Deleting Lessons

**Via conversation**:
```
You: That lesson about inline styles is wrong now, we allow them in the
     new design system. Remove it.

Claude: [Searches for the lesson, confirms with user]
        Found lesson #156: "Never use inline styles in this codebase..."
        Removed. The embedding index will be rebuilt on next search.
```

**Via negative feedback** (see Section 5):
```
You: That lesson you just injected about Picasso buttons is outdated.

Claude: [Marks lesson as deprecated, removes from active index]
        Marked lesson #89 as deprecated. It won't appear in future searches.
```

---

## 3. How Does the User See What Lessons Were Injected?

### Transparent by Default, Details on Demand

**Default behavior**: Lessons are injected via `additionalContext` in the
`UserPromptSubmit` hook. This adds them discretely to context -- they appear in
Claude's working memory but are NOT displayed in the chat transcript.

This is intentional. Most of the time, the user does not care which specific lessons
were loaded. They just want Claude to behave correctly.

**On-demand visibility**: When the user wants to see what was injected:

```
You: What lessons did you use for that last response?

Claude: I had 3 lessons in context for your last prompt:
        1. [#156] "Never use inline styles -- use CSS classes or Picasso props"
           (category: development/frontend/styling, relevance: 0.91)
        2. [#34] "Check existing table implementations before creating new ones"
           (category: development/frontend/code-patterns, relevance: 0.78)
        3. [#201] "Use yarn test --ci in CI environments"
           (category: devops/ci-cd, relevance: 0.62)
```

**Implementation**: The hook script writes the injected lesson IDs + scores to a
small state file (`~/.claude/lessons/.last-search.json`). A skill or MCP tool can
read this file and report what was injected.

### Visibility Levels

Configure in `~/.claude/lessons/config.json`:

```json
{
  "visibility": "silent",  // Options: "silent", "summary", "verbose"
  "min_relevance": 0.65,
  "max_lessons_per_prompt": 5
}
```

- **silent** (default): Lessons injected via additionalContext, no transcript output
- **summary**: One-line note in transcript: "3 lessons loaded (styling, ci-cd, git)"
- **verbose**: Full lesson text shown in transcript before Claude's response

### Status Line Integration

The existing `gsd-statusline.js` pattern could be extended:

```
[GSD: On Track] [Lessons: 3 matched, 847 total]
```

This gives passive awareness without cluttering the conversation.

---

## 4. How Does Category Assignment Work?

### Hierarchical Category Taxonomy

```
development/
  frontend/
    styling       -- CSS, Picasso, design system, responsive
    components    -- React components, patterns, props
    testing       -- Jest, RTL, Storybook, Happo
    state         -- Redux, Apollo, React Query
    performance   -- Bundle size, lazy loading, memoization
  backend/
    graphql       -- Schema, resolvers, code generation
    api           -- REST, endpoints, authentication
  tooling/
    build         -- Webpack, Vite, compilation
    linting       -- ESLint, Prettier, TypeScript strict mode

product-management/
  jira            -- Tickets, workflows, project keys
  linear          -- Issues, cycles, labels
  process         -- Sprint planning, estimation, standups

devops/
  ci-cd           -- GitHub Actions, deployment, pipelines
  infrastructure  -- AWS, Docker, environments
  monitoring      -- Sentry, logging, alerting

acme/
  conventions     -- Branch naming, PR format, code review
  platform        -- App repo specifics, monorepo structure
  workflow        -- Acme-specific development process

tools/
  claude-code     -- Hooks, skills, MCP, configuration
  figma           -- Design handoff, MCP integration
  git             -- Branching, merging, rebasing
  browser         -- Playwright, DevTools, debugging
```

### Auto-Assignment (Default)

When a lesson is extracted or added, assign category automatically:

**V1 (keyword-based)**:
Simple keyword mapping. Fast, deterministic, no API calls.

```python
CATEGORY_KEYWORDS = {
    "development/frontend/styling": ["css", "style", "picasso", "design system", "responsive"],
    "devops/ci-cd": ["ci", "github actions", "pipeline", "deploy", "cd"],
    "acme/conventions": ["branch", "pr", "pull request", "commit", "naming"],
    # ...
}
```

The keyword approach works well for the existing 15 lessons and scales to hundreds.
It fails gracefully: unmatched lessons go to a "general" category.

**V2 (embedding-based)**:
Each category has a centroid embedding (average of all lesson embeddings in that
category). New lessons are assigned to the nearest centroid. This handles edge cases
the keyword approach misses.

**V3 (Claude-assisted)**:
For ambiguous lessons, ask Claude to classify:
```
Lesson: "ExitPlanMode requires explicit user confirmation"
Keywords match: none
Embedding nearest: tools/claude-code (0.71), acme/conventions (0.68)
-> Ask Claude: "tools/claude-code" (confidence: high)
```

### Manual Override

Users can always override:
```
You: Move lesson #156 from development/frontend/styling to acme/conventions

Claude: Moved lesson #156 to acme/conventions. Re-indexed.
```

### Category Discovery

New categories should emerge organically. If many lessons cluster in a region that
does not match existing categories, surface this:

```
You: /lessons stats

Claude: Category distribution:
  development/frontend/styling    -- 42 lessons
  acme/conventions              -- 38 lessons
  devops/ci-cd                    -- 27 lessons
  ...
  Uncategorized                   -- 12 lessons

  Suggestion: 8 uncategorized lessons relate to "monorepo structure"
  (yarn workspaces, package boundaries, shared libs).
  Create new category development/tooling/monorepo? (y/n)
```

---

## 5. What's the Feedback Loop? How Do Bad Lessons Get Removed?

### The Problem

Bad lessons are more dangerous than no lessons. A wrong lesson ("always use inline
styles for dynamic values") actively causes harm. The system needs a way to identify
and remove bad lessons without requiring the user to audit the database.

### Passive Feedback: Relevance Decay

Each lesson tracks:
- `last_matched`: timestamp of last time it was returned as a search result
- `times_matched`: total number of times returned
- `created_at`: when the lesson was first added
- `occurrence_count`: how many sessions contributed to this lesson

Lessons that are never matched decay naturally. A monthly cleanup job can flag
lessons that have not matched in 90 days:

```
You: /lessons cleanup

Claude: Found 23 lessons not matched in 90+ days:
  - [#12] "Use yarn start:local for local development" (last matched: 2025-11-01)
  - [#45] "Apollo cache requires manual eviction after mutations" (last matched: 2025-10-15)
  ...
  Archive these 23 lessons? They'll be removed from search but kept in history.
```

### Active Feedback: Contradiction Detection

When a user explicitly contradicts a lesson:

```
You: Actually, we DO use inline styles now with the new CSS-in-JS setup.

Claude: [Detects contradiction with lesson #156]
        I have a stored lesson that says "Never use inline styles."
        Should I update or remove this lesson?

You: Remove it.

Claude: Removed lesson #156. Future sessions won't see this advice.
```

**Implementation**: This is hard to do automatically in V1. In V2 (MCP), Claude can
call `deprecate_lesson(id, reason)` when it detects a contradiction. The lesson gets
soft-deleted (marked deprecated, excluded from search, but kept in history).

### Active Feedback: Explicit Thumbs Up/Down

After Claude uses a lesson:

```
You: That tip about yarn test --ci saved me time, thanks.
     (or: That lesson about branch naming is wrong.)
```

Claude can interpret these signals and call `rate_lesson(id, positive=True)` or
`rate_lesson(id, positive=False)`.

Lessons with negative ratings get flagged for review. Lessons with consistent
positive ratings get boosted in search relevance.

### Automated Quality Checks

Run periodically (e.g., weekly via cron or session start):

1. **Duplicate detection**: Embed all lessons, find pairs with cosine similarity
   > 0.92. Flag for merging.
2. **Staleness check**: Lessons older than 6 months with low match count.
3. **Contradiction detection**: Lessons in the same category with opposing
   recommendations (e.g., "always use X" vs "never use X").
4. **Category drift**: Lessons whose embedding is far from their category centroid
   (possible miscategorization).

---

## 6. How Does This Compose with AGENTS.md / lessons-learned.md?

### Current Setup

```
~/.claude/AGENTS.md
  -> Reads project AGENTS.md
  -> Reads ~/.shared-cli-agents/AGENTS.md
     -> Conditionally loads frontend-acme.md, codestyle.md, acme-workflow.md
     -> Always loads lessons-learned.md

~/.shared-cli-agents/lessons-learned.md (flat file, ~15 lessons)
  -> Generated by extract-lessons.py on SessionStart
  -> ALL lessons injected into context every session
```

### Migration Path

**Phase 1: Shadow mode (no user-visible changes)**

The new semantic search runs alongside the existing flat file. The hook injects
lessons from the new system via `additionalContext`, while the old
`lessons-learned.md` continues to be read via AGENTS.md. This lets us validate that
the new system returns the RIGHT lessons before removing the old one.

```
SessionStart hook:
  -> extract-lessons.py (existing, still generates lessons-learned.md)
  -> import-to-db.py (NEW: imports extracted lessons into SQLite + numpy)

UserPromptSubmit hook:
  -> search-lessons.py (NEW: semantic search, injects additionalContext)

AGENTS.md still references lessons-learned.md (unchanged)
```

**Phase 2: Cut over**

Once validated, update AGENTS.md:

```markdown
## Lessons learned

- Lessons are automatically searched and injected per-prompt by the semantic
  search system. No need to read a static file.
- To see what lessons were used: ask "what lessons did you use?"
- To add a lesson: tell Claude to remember something
- To manage lessons: /lessons status
```

Remove the `lessons-learned.md` reference from `~/.shared-cli-agents/AGENTS.md`.
The flat file can remain as a human-readable export but is no longer the source of
truth.

**Phase 3: Full integration**

The AGENTS.md conditional loading system becomes another consumer of the semantic
search. Instead of loading `frontend-acme.md` every time a React project is
detected, the relevant conventions from that file are indexed as lessons in the
`acme/conventions` and `development/frontend/*` categories. They get injected
only when relevant.

This is a bigger change and should be approached carefully, since AGENTS.md files
contain both "always applicable" rules (which should always be in context) and
"sometimes relevant" knowledge (which benefits from semantic search).

**Proposed split**:
- **AGENTS.md**: Core rules that ALWAYS apply (non-negotiable principles, workflow
  requirements). Stays as-is, always loaded.
- **Lessons DB**: Specific, contextual knowledge that is relevant SOMETIMES.
  Searched and injected per-prompt.

### File Layout

```
~/.claude/
  settings.json           -- hooks configuration
  lessons/
    lessons.db            -- SQLite: lessons, categories, metadata
    lessons.npy           -- memory-mapped embeddings
    config.json           -- visibility, thresholds, model config
    manage.py             -- CLI for import/export/edit
    search.py             -- called by UserPromptSubmit hook
    .last-search.json     -- last search results for introspection
  skills/
    lessons/
      SKILL.md            -- /lessons skill definition
  mcp-servers/            -- V2
    lesson-search/
      server.py           -- MCP server implementation

~/.shared-cli-agents/
  AGENTS.md               -- updated to reference semantic search
  extract-lessons.py      -- still extracts from facets, now feeds into lessons.db
  lessons-learned.md      -- deprecated (kept as human-readable export)
```

---

## 7. The Ideal User Journey

### Day 1: Installation

```
You: Set up the lesson search system.

Claude: [Reads SKILL.md for /lessons setup]
        Installing dependencies: fastembed, rank-bm25, numpy
        Importing 15 existing lessons from lessons-learned.md...
        Generating embeddings... done (15 lessons, 384 dimensions)
        Configuring UserPromptSubmit hook...

        Lesson search is active. Your existing 15 lessons are indexed.
        New lessons from session analysis will be automatically added.

        Commands:
          /lessons status  -- system health and stats
          /lessons export  -- export to markdown for editing
          /lessons import  -- re-import after editing
```

### Day 30: Natural use

```
You: Add a Happo visual test for the new JobCard component

Claude: [Hook fires, searches "happo visual test component"]
        [Injects lessons about Storybook-driven UI, Happo integration patterns]

        I'll create a Happo visual test for JobCard. Based on the project
        conventions, I'll add a Storybook story first and configure Happo
        to capture it...
```

The user never had to think about lessons. Claude just did the right thing because
the right knowledge was in context.

### Day 90: Maintenance

```
You: /lessons stats

Claude: Lesson search system:
        Total lessons: 312
        Categories: 18
        Most active: development/frontend/styling (47 lessons)
        Least active: devops/monitoring (3 lessons)
        Average relevance score: 0.74
        Lessons matched today: 23

        Suggestions:
        - 5 lessons have contradicting advice about CSS modules vs Picasso.
          Run /lessons review contradictions to resolve.
        - 12 lessons haven't matched in 60+ days. Run /lessons cleanup to review.
```

---

## Sources

- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
- [Claude Code Skills System](https://code.claude.com/docs/en/skills)
- [Claude Code Hook Configuration Guide](https://claude.com/blog/how-to-configure-hooks)
- [UserPromptSubmit Hook DeepWiki](https://deepwiki.com/thedotmack/claude-mem/3.1.2-userpromptsubmit-hook)
- [Claude Code Hooks Mastery](https://github.com/disler/claude-code-hooks-mastery)
- [Claude Code Customization Guide](https://alexop.dev/posts/claude-code-customization-guide-claudemd-skills-subagents/)
