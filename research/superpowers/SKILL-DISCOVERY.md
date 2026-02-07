# Semantic Lesson Search: Skill Discovery Deep Dive

## What Is a "Skill" in This Context?

Claude Code has a multi-layered extensibility system. "Skill" means different things
at different layers:

### Layer 1: Claude Code Skills (`.claude/skills/`)

These are directories containing a `SKILL.md` entrypoint plus optional supporting
files (templates, examples, scripts). They are auto-discovered by Claude Code and
can be invoked as slash commands.

Current skills in this setup:
```
~/.claude/skills/
  gh-create-pr-acme/   -- Create PRs following Acme conventions
  gh-read-comments/      -- Read and summarize PR comments
  jira/                  -- Interact with Jira (create, update, query)
  linear/                -- Interact with Linear
  netlify-deploy/        -- Deploy to Netlify
  pdf/                   -- Read and analyze PDFs
  playwright/            -- Browser automation and testing
  sentry/                -- Error tracking and debugging
  spreadsheet/           -- Read and manipulate spreadsheets
```

**Characteristics**: Procedural (do X then Y), invoked explicitly or auto-matched
by description, contain instructions not just knowledge.

### Layer 2: MCP Tools

Tools exposed by MCP servers. Currently configured:
- Playwright (browser automation)
- Chrome DevTools (debugging)
- Context7 (documentation lookup)
- Figma (design implementation)
- Sentry (error tracking)
- Linear (project management)
- Slack (communication)
- GitHub (repository operations)

**Characteristics**: Atomic operations (click, navigate, search), always available
when server is connected, no complex instructions.

### Layer 3: Custom Scripts and Hooks

Scripts that extend Claude's behavior:
- `extract-lessons.py` (session analysis)
- `gsd-check-update.js` (status tracking)
- `gsd-statusline.js` (status display)

**Characteristics**: Automated, not directly invoked by Claude, infrastructure-level.

### Layer 4: Knowledge Files

Markdown files that provide context:
- `AGENTS.md` files (project rules)
- `frontend-acme.md`, `codestyle.md` (conventions)
- `lessons-learned.md` (extracted knowledge)

**Characteristics**: Passive (injected into context), no actions, pure knowledge.

### The Unified View

For skill discovery, all four layers need to be searchable:

| Layer | "What can help with this?" | Example |
|-------|---------------------------|---------|
| Skills | "Use /jira to create that ticket" | User says "create a TAPS ticket" |
| MCP Tools | "Use figma:implement-design" | User says "implement the sidebar design" |
| Scripts | (Not directly invocable) | N/A |
| Knowledge | "Here's what you need to know..." | User asks about styling approach |

---

## How Would Skills Be Indexed Alongside Lessons?

### The Shared Index Architecture

Skills and lessons live in the same search infrastructure but are typed differently:

```
lessons.db (SQLite)
  table: entries
    id          INTEGER PRIMARY KEY
    type        TEXT       -- "lesson" | "skill" | "mcp_tool" | "knowledge"
    title       TEXT       -- short name or description
    content     TEXT       -- full text for BM25 search
    category    TEXT       -- hierarchical category
    metadata    JSON       -- type-specific metadata
    created_at  TIMESTAMP
    updated_at  TIMESTAMP
    active      BOOLEAN

lessons.npy (memory-mapped)
  -- embeddings for ALL entry types, indexed by entry.id
```

### Indexing Skills

Each skill directory gets indexed by its `SKILL.md` content plus filenames:

```python
# For ~/.claude/skills/jira/SKILL.md
{
    "type": "skill",
    "title": "jira",
    "content": "Create, update, and query Jira tickets. "
               "Follows Acme conventions for TAPS project. "
               "Supports creating subtasks, adding comments, "
               "transitioning ticket status...",
    "category": "tools/jira",
    "metadata": {
        "invocation": "/jira",
        "path": "~/.claude/skills/jira/",
        "auto_match": true,
        "files": ["SKILL.md", "templates/ticket.md"]
    }
}
```

### Indexing MCP Tools

Each MCP tool gets indexed by its name + description:

```python
# For figma:implement-design
{
    "type": "mcp_tool",
    "title": "figma:implement-design",
    "content": "Implement a design from Figma. Takes a Figma URL "
               "or frame name and generates React components "
               "matching the design. Uses Picasso components "
               "where applicable.",
    "category": "tools/figma",
    "metadata": {
        "server": "figma",
        "tool_name": "implement-design",
        "parameters": ["url", "frame_name"]
    }
}
```

### Indexing Knowledge Files

Conventions and rules from markdown files, chunked by section:

```python
# For frontend-acme.md, section on component patterns
{
    "type": "knowledge",
    "title": "Acme Frontend: Component Patterns",
    "content": "Use Picasso components by default. Custom UI must "
               "be justified. Every component needs a Storybook story. "
               "Use StoryShell for page-level stories...",
    "category": "acme/conventions",
    "metadata": {
        "source_file": "~/.shared-cli-agents/frontend-acme.md",
        "section": "Component Patterns",
        "always_load": false
    }
}
```

### Re-indexing Strategy

Skills and MCP tools change infrequently. Re-index on:
- Session start (check file mtimes, re-index if changed)
- Explicit `/lessons reindex` command
- When a new MCP server is added to settings

Lessons change more frequently. Re-index on:
- New lesson added (append to numpy array, no full rebuild)
- Lesson edited or deleted (rebuild affected entries)
- Periodic full rebuild (weekly, catches any inconsistencies)

---

## How Would the System Decide Between Skills and Lessons?

### The Core Routing Problem

User says: "Create a PR for the sidebar changes"

The system finds:
1. **Skill**: `/gh-create-pr-acme` (relevance: 0.89) -- procedural, creates a PR
2. **Lesson**: "PR descriptions: max 50 words, no co-authored-by" (relevance: 0.85) -- knowledge
3. **Lesson**: "Branch naming: taps-NUMBER lowercase" (relevance: 0.78) -- knowledge
4. **MCP Tool**: `github:create_pull_request` (relevance: 0.72) -- atomic operation

All four are relevant, but they serve different purposes. The system needs to present
them appropriately.

### Decision Matrix

```
                        Action Intent?
                       /            \
                    Yes              No
                   /                  \
           Has matching              Return as
           skill?                    additionalContext
          /          \               (lessons + knowledge)
        Yes           No
       /               \
  Suggest skill    Return MCP tools
  + inject lessons as actionable
  as context       alternatives
```

### Implementation: Typed Results

The search returns typed results, and the injection logic handles each type
differently:

```python
results = search(query="create a PR for sidebar changes", limit=5)

# Results come back typed:
# [
#   {"type": "skill",    "id": 42,  "score": 0.89, "title": "gh-create-pr-acme"},
#   {"type": "lesson",   "id": 156, "score": 0.85, "content": "PR descriptions: max 50 words..."},
#   {"type": "lesson",   "id": 201, "score": 0.78, "content": "Branch naming: taps-NUMBER..."},
#   {"type": "mcp_tool", "id": 301, "score": 0.72, "title": "github:create_pull_request"},
# ]

# Injection logic:
context_parts = []

for result in results:
    if result["type"] == "skill":
        context_parts.append(
            f"AVAILABLE SKILL: /{result['title']} -- "
            f"consider using this skill for the current task"
        )
    elif result["type"] == "lesson":
        context_parts.append(
            f"LESSON: {result['content']}"
        )
    elif result["type"] == "mcp_tool":
        context_parts.append(
            f"AVAILABLE TOOL: {result['title']} -- "
            f"this MCP tool may be relevant"
        )
    elif result["type"] == "knowledge":
        context_parts.append(
            f"CONVENTION: {result['content']}"
        )
```

### Priority and Deduplication

When a skill and a lesson cover the same ground (e.g., `/jira` skill and a lesson
about Jira project naming), the system should:

1. **Prefer the skill** for action-oriented prompts ("create a ticket")
2. **Prefer the lesson** for knowledge-oriented prompts ("what's the project key?")
3. **Include both** when the skill benefits from the lesson as context

Detection heuristic: If the user's prompt contains action verbs (create, deploy,
test, run, check, fix), weight skills higher. If it contains question words (what,
how, why, which) or knowledge markers (convention, rule, pattern), weight lessons
higher.

---

## Multi-Modal Matching: Prompt -> Skills + Lessons + Documentation

### The Full Retrieval Pipeline

```
User prompt: "add happo visual tests for the new JobCard component"
                              |
                              v
                    +---------+---------+
                    |  Embed query      |
                    |  (FastEmbed, 10ms)|
                    +---------+---------+
                              |
              +---------------+---------------+
              |               |               |
              v               v               v
        Vector Search    BM25 Search    Category Filter
        (numpy, <1ms)   (rank_bm25)   (keyword heuristic)
              |               |               |
              v               v               v
        +-----+-----+  +-----+-----+  +------+------+
        | Semantic   |  | Keyword   |  | Category    |
        | matches    |  | matches   |  | boost       |
        +-----+-----+  +-----+-----+  +------+------+
              |               |               |
              +-------+-------+-------+-------+
                      |
                      v
              +-------+-------+
              | Reciprocal    |
              | Rank Fusion   |
              +-------+-------+
                      |
                      v
              +-------+-------+
              | Type-aware    |
              | ranking       |
              +-------+-------+
                      |
                      v
              +-------+-------+
              | Format for    |
              | injection     |
              +-------+-------+
                      |
                      v
            additionalContext:
              AVAILABLE SKILL: /playwright -- browser testing automation
              LESSON: Use Storybook-driven approach for visual testing
              LESSON: Happo captures happen via Storybook stories, not direct page screenshots
              CONVENTION: Every new component needs a Storybook story (AGENTS.md)
```

### Relevance Scoring Across Types

Different entry types have different relevance profiles. A skill with 0.75 cosine
similarity is more actionable than a lesson with 0.80 similarity, because skills
represent concrete capabilities.

**Scoring formula**:
```
final_score = (
    vector_similarity * 0.5
    + bm25_score_normalized * 0.3
    + category_boost * 0.1
    + type_boost * 0.1
)

# Type boosts (when action intent detected):
type_boosts = {
    "skill": 0.15,
    "mcp_tool": 0.10,
    "lesson": 0.00,
    "knowledge": -0.05,
}

# Type boosts (when knowledge intent detected):
type_boosts = {
    "skill": 0.00,
    "mcp_tool": -0.05,
    "lesson": 0.10,
    "knowledge": 0.15,
}
```

### Context Budget Management

The system has a context budget (measured in tokens, not entries). Each result has a
different token cost:

- Skill suggestion: ~20 tokens ("AVAILABLE SKILL: /jira -- create Jira tickets")
- Lesson: ~30-60 tokens (the lesson text itself)
- Knowledge chunk: ~50-200 tokens (convention details)
- MCP tool suggestion: ~15 tokens ("AVAILABLE TOOL: figma:implement-design")

The system fills the budget greedily by final_score / token_cost ratio, maximizing
information density:

```python
MAX_CONTEXT_TOKENS = 500  # configurable

budget_remaining = MAX_CONTEXT_TOKENS
selected = []
for result in sorted(results, key=lambda r: r["score"] / r["token_cost"], reverse=True):
    if result["token_cost"] <= budget_remaining:
        selected.append(result)
        budget_remaining -= result["token_cost"]
```

---

## Could This Become an Intelligent Routing Layer?

### Vision: The Knowledge Router

Instead of separate systems for lessons, skills, documentation, and conventions,
build a unified knowledge router that sits between the user and Claude:

```
User message
     |
     v
+----+----+
| Knowledge|
| Router   |
+----+----+
     |
     +-- Skills to suggest
     +-- Lessons to inject
     +-- Conventions to remind
     +-- Documentation to reference
     +-- MCP tools to highlight
     +-- Warnings to surface ("last time you tried this, X happened")
     |
     v
Claude (with enriched context)
```

### Why This Is Powerful

1. **Learning from failure**: "Last time you changed the sidebar CSS, it broke the
   mobile layout. The lesson says to check responsive breakpoints." This is not just
   knowledge -- it is contextual warning.

2. **Proactive skill suggestion**: "You are about to create a PR manually. The
   `/gh-create-pr-acme` skill handles branch naming, PR description format, and
   Acme conventions automatically." This saves time the user did not even know
   they were about to waste.

3. **Documentation JIT**: "You are working with the GraphQL schema. Here are the
   relevant type definitions from the generated types file." Instead of loading all
   documentation, load precisely what is needed.

4. **Cross-project knowledge**: If the same lesson search indexes lessons from
   multiple projects (app-repo, other repos), knowledge transfers automatically.
   A lesson learned in one project applies to another.

### Architecture for the Routing Layer

```
MCP Server: knowledge-router
  |
  +-- search(query, types?, categories?, limit?)
  |     Returns: mixed results (skills + lessons + knowledge + tools)
  |
  +-- suggest_for_prompt(prompt)
  |     Returns: curated set of most relevant items, pre-formatted
  |     This is what the UserPromptSubmit hook calls
  |
  +-- learn(text, category?, source?)
  |     Adds a new lesson to the index
  |
  +-- forget(id)
  |     Removes an entry from the index
  |
  +-- index_skills()
  |     Re-indexes all skills from ~/.claude/skills/
  |
  +-- index_mcp_tools()
  |     Re-indexes all MCP tool descriptions
  |
  +-- index_knowledge(file_path)
  |     Indexes a markdown file as knowledge chunks
  |
  +-- explain(id)
  |     Shows full details about any indexed entry
  |
  +-- stats()
  |     Returns index statistics, category distribution
```

### Indexing Pipeline

```
Sources                    Index              Query Path
--------                   -----              ----------
~/.claude/skills/*    -->  |             |
MCP server configs    -->  | SQLite DB   | <-- UserPromptSubmit hook
AGENTS.md files       -->  | + numpy     |     (top 3, fast)
Convention files      -->  | embeddings  | <-- MCP search tool
lessons-learned.md    -->  | + BM25      |     (full search, on demand)
Session facets        -->  |             |
```

### Self-Improving Loop

The routing layer can improve itself:

1. **Track which results Claude actually uses**: If Claude receives 5 context items
   but only references 2 in its response, the other 3 were noise. Reduce their
   relevance for similar future queries.

2. **Track user corrections**: When the user says "no, don't use that approach" after
   Claude follows a lesson, mark that lesson as potentially outdated.

3. **Observe tool usage patterns**: If Claude consistently calls
   `figma:implement-design` when working on UI tasks, boost the Figma tools for UI
   prompts even if the user does not mention Figma.

4. **Session-aware context**: The routing layer knows what has already been injected
   in this session. It does not repeat the same lessons across multiple prompts in
   the same conversation.

### Session-Aware State

```python
class SessionState:
    """Track what has been injected in this session to avoid repetition."""

    def __init__(self):
        self.injected_ids: set[int] = set()
        self.prompt_history: list[str] = []
        self.session_categories: set[str] = set()

    def filter_results(self, results: list[dict]) -> list[dict]:
        """Remove already-injected entries, boost session-relevant categories."""
        filtered = []
        for r in results:
            if r["id"] in self.injected_ids:
                continue  # already seen this session
            if r["category"] in self.session_categories:
                r["score"] *= 1.1  # boost same-category results
            filtered.append(r)
        return filtered
```

---

## Concrete Implementation Roadmap

### Phase 1: Lesson Search Only (1 weekend)

- `search.py`: FastEmbed + numpy + BM25 hybrid search
- `UserPromptSubmit` hook calls `search.py` with the prompt
- Import existing 15 lessons from `lessons-learned.md`
- Auto-extract new lessons from session facets (existing flow)
- Output: `additionalContext` with top-3 relevant lessons

### Phase 2: Add Skill Indexing (1 week)

- Index `~/.claude/skills/*/SKILL.md` files into the same DB
- Index MCP tool descriptions (read from settings.json / MCP configs)
- Type-aware result formatting (skills as suggestions, lessons as knowledge)
- `/lessons status` skill for health checking

### Phase 3: MCP Server (2 weeks)

- Wrap search backend in an MCP server
- Expose `search`, `learn`, `forget`, `stats` tools
- Keep `UserPromptSubmit` hook as a fast path (calls same backend)
- Add session-aware state tracking

### Phase 4: Knowledge Router (1 month)

- Index AGENTS.md, convention files, documentation
- Multi-modal matching with context budget management
- Self-improving relevance via usage tracking
- Contradiction detection and automated cleanup
- Cross-project knowledge sharing

### Phase 5: Intelligent Agent (future)

- The router becomes an agent that can reason about what knowledge to inject
- Instead of pure similarity matching, it considers the conversation state,
  the project being worked on, and the user's history
- It can proactively surface warnings: "The last 3 times you deployed on Friday
  afternoon, there were rollback issues"

---

## Key Design Decisions Summary

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Skills and lessons in same index? | Yes | Enables unified search and cross-type ranking |
| Same embedding model for all types? | Yes | Ensures embedding space compatibility |
| Skills auto-discovered? | Yes, on session start | Skills change rarely, re-index is cheap |
| MCP tools auto-indexed? | Yes, from config | Config is the source of truth for available tools |
| Knowledge files chunked? | Yes, by section | Full files are too large; sections are semantic units |
| Type-aware scoring? | Yes | Actions and knowledge need different ranking |
| Session-aware dedup? | Yes | Prevents repetitive context injection |
| Cross-project? | Phase 4+ | Same infrastructure, just add project scoping |

---

## Sources

- [Claude Code Skills Documentation](https://code.claude.com/docs/en/skills)
- [Claude Code Skill System DeepWiki](https://deepwiki.com/anthropics/claude-code/3.7-custom-slash-commands)
- [Skills vs Slash Commands Unified System](https://yingtu.ai/blog/claude-code-skills-vs-slash-commands)
- [Claude Code Customization Guide](https://alexop.dev/posts/claude-code-customization-guide-claudemd-skills-subagents/)
- [MCP Tool Search Lazy Loading](https://code.claude.com/docs/en/mcp)
- [Claude Context: Semantic Code Search MCP](https://github.com/zilliztech/claude-context)
- [Qdrant MCP Server](https://github.com/qdrant/mcp-server-qdrant)
- [mcp-vector-search](https://github.com/bobmatnyc/mcp-vector-search)
- [Hybrid BM25 + Vector Search](https://medium.com/@aunraza021/combining-bm25-vector-search-a-hybrid-approach-for-enhanced-retrieval-performance-a374b4ba4644)
- [FastEmbed](https://github.com/qdrant/fastembed)
- [USearch Single-File Vector Search](https://github.com/unum-cloud/USearch)
