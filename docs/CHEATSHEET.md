# Engrammar Cheatsheet

Quick reference for common Engrammar operations.

## Table of Contents

- [CLI Commands](#cli-commands)
- [MCP Tools](#mcp-tools)
- [Tag System](#tag-system)
- [Prerequisites](#prerequisites)
- [Search Tips](#search-tips)
- [Common Workflows](#common-workflows)

---

## CLI Commands

### Setup & Status

```bash
# Initialize database and build index
engrammar setup

# Show system status and environment
engrammar status

# Show detected tags for current directory
engrammar detect-tags

# Rebuild embedding index
engrammar rebuild
```

### Search

```bash
# Basic search
engrammar search "component patterns"

# Search with category filter
engrammar search "api error" --category development/backend

# Search with tag filter
engrammar search "state management" --tags react

# Search with multiple tags (AND logic)
engrammar search "ui component" --tags acme,react,frontend
```

### Add Lessons

```bash
# Basic add
engrammar add "Always use TypeScript for new components"

# Add with category
engrammar add "Use Picasso components" --category development/frontend

# Add with tags
engrammar add "Follow Acme's React patterns" --tags acme,react,frontend

# Add with category and tags
engrammar add "Use Rails engines for domain isolation" \
  --category development/backend/architecture \
  --tags acme,ruby,rails,monorepo
```

### List & Browse

```bash
# List all lessons
engrammar list

# List with pagination
engrammar list --limit 10 --offset 0

# List by category
engrammar list --category development/frontend

# Show specific category lessons
engrammar list --category tools/figma
```

### Update Lessons

```bash
# Update text
engrammar update 42 --text "New lesson text"

# Update category
engrammar update 42 --category development/frontend/hooks

# Update prerequisites
engrammar update 42 --prereqs '{"tags":["react","hooks"]}'
```

### Pin Management

```bash
# Pin lesson (always show at session start)
engrammar pin 42

# Unpin lesson
engrammar unpin 42

# Pin with prerequisites
# (manually - through update command)
engrammar update 42 --prereqs '{"tags":["frontend"]}'
engrammar pin 42
```

### Deprecate

```bash
# Mark lesson as outdated
engrammar deprecate 42
```

### Import/Export

```bash
# Export all lessons to markdown
engrammar export > lessons.md

# Import from file
engrammar import lessons.json
```

---

## MCP Tools

Use these from within Claude Code sessions:

### Search

```python
# Basic search
engrammar_search(query="component patterns")

# Search with tags
engrammar_search(query="state management", tags=["react"])

# Search with category
engrammar_search(query="api error", category="development/backend")

# Limit results
engrammar_search(query="testing", top_k=10)
```

### Add

```python
# Basic add
engrammar_add(
    text="Use Picasso for all UI components",
    category="development/frontend"
)

# Add with tags
engrammar_add(
    text="Follow Acme's React patterns",
    category="development/frontend",
    tags=["acme", "react", "frontend"]
)

# Add with full prerequisites
engrammar_add(
    text="Use specific Figma components",
    category="tools/figma",
    tags=["acme", "figma"],
    prerequisites={"mcp_servers": ["figma"]}
)
```

### Feedback

```python
# Mark lesson as useful
engrammar_feedback(
    lesson_id=42,
    applicable=True,
    reason="Helped avoid state management bug"
)

# Mark as not applicable with reason
engrammar_feedback(
    lesson_id=42,
    applicable=False,
    reason="Project doesn't use Figma"
)

# Add prerequisites based on feedback
engrammar_feedback(
    lesson_id=42,
    applicable=False,
    reason="Only relevant in Acme projects",
    add_prerequisites={"tags": ["acme"]}
)
```

### Update

```python
# Update text
engrammar_update(lesson_id=42, text="Updated lesson text")

# Update category
engrammar_update(lesson_id=42, category="development/frontend/hooks")

# Update prerequisites
engrammar_update(
    lesson_id=42,
    prerequisites={"tags": ["react", "hooks"]}
)
```

### Pin/Unpin

```python
# Pin lesson
engrammar_pin(lesson_id=42)

# Pin with prerequisites
engrammar_pin(
    lesson_id=42,
    prerequisites={"tags": ["frontend", "react"]}
)

# Unpin
engrammar_unpin(lesson_id=42)
```

### List

```python
# List all lessons
engrammar_list()

# List by category
engrammar_list(category="development/frontend")

# List with pagination
engrammar_list(limit=10, offset=20)

# Include deprecated
engrammar_list(include_deprecated=True)
```

### Status

```python
# Show system status
engrammar_status()
# Shows: lesson count, categories, environment, detected tags
```

### Deprecate

```python
# Mark as outdated
engrammar_deprecate(lesson_id=42, reason="Outdated pattern")
```

---

## Tag System

### Auto-Detected Tags

Tags are automatically detected from:

| Source | Examples |
|--------|----------|
| **Paths** | `~/work/acme/*` → `acme` |
| **Git remote** | `github.com/acme` → `github`, `acme` |
| **File markers** | `tsconfig.json` → `typescript` |
| **package.json** | `"react": "^18"` → `react`, `frontend` |
| **Gemfile** | `gem 'rails'` → `rails`, `backend` |
| **Directories** | `packages/` → `monorepo` |

### Common Tags

**Languages & Frameworks:**
- `typescript`, `javascript`, `ruby`, `python`, `golang`, `rust`
- `react`, `vue`, `angular`, `nextjs`, `nuxtjs`
- `rails`, `nodejs`, `nestjs`

**Tools & Services:**
- `docker`, `jest`, `playwright`, `cypress`, `rspec`
- `github`, `bitbucket`, `gitlab`
- `figma`, `jira`, `linear`

**Project Types:**
- `frontend`, `backend`, `fullstack`
- `monorepo`, `rails-engines`

**Organizations:**
- `acme`, `personal`
- Custom: add to `tag_patterns.py`

**Acme-Specific:**
- `picasso` (design system)
- `davinci` (build tools)
- `topkit` (shared packages)

### Manual Tagging

```bash
# CLI
engrammar add "Lesson text" --tags frontend,react,typescript

# MCP
engrammar_add(text="Lesson text", tags=["frontend", "react", "typescript"])
```

### Tag-Based Search

```bash
# Find React-related lessons
engrammar search "hooks" --tags react

# Find Acme frontend lessons
engrammar search "component" --tags acme,frontend

# MCP version
engrammar_search(query="hooks", tags=["react"])
```

### Auto-Pin Behavior

When a lesson reaches **15 matches** across different tag contexts:

```
Example:
- 6 matches in ['acme', 'frontend', 'typescript']
- 5 matches in ['acme', 'frontend', 'react']
- 4 matches in ['personal', 'frontend', 'typescript']

→ Common tag 'frontend' has 15 matches
→ Auto-pins with {"tags": ["frontend"]}
→ Now shows in ALL 'frontend' projects
```

---

## Prerequisites

### Structure

```json
{
  "os": ["darwin", "linux"],
  "repos": ["app-repo", "picasso"],
  "tags": ["frontend", "react"],
  "paths": ["~/work/acme"],
  "mcp_servers": ["figma", "linear"]
}
```

### Match Logic

- **os**: Must match current OS
- **repos**: Must be in one of the repos
- **tags**: Must have ALL specified tags
- **paths**: Current directory must start with one of the paths
- **mcp_servers**: Must have all specified MCP servers configured

### Examples

```python
# Only show in macOS
prerequisites={"os": ["darwin"]}

# Only in specific repos
prerequisites={"repos": ["app-repo", "picasso"]}

# Only in React projects
prerequisites={"tags": ["react"]}

# Only in Acme frontend projects
prerequisites={"tags": ["acme", "frontend"]}

# Only when Figma MCP is available
prerequisites={"mcp_servers": ["figma"]}

# Combined
prerequisites={
    "tags": ["acme", "react"],
    "repos": ["app-repo"],
    "os": ["darwin"]
}
```

---

## Search Tips

### Query Strategies

**Keywords:**
```bash
# Use specific terms
engrammar search "useState useEffect"
engrammar search "Rails engine domain"
```

**Natural Language:**
```bash
# Ask questions
engrammar search "how to handle API errors"
engrammar search "component state management patterns"
```

**Tool-Specific:**
```bash
# Match tool usage
engrammar search "Edit file patterns"
engrammar search "Bash git commands"
```

### Filtering

**By Category:**
```bash
engrammar search "patterns" --category development/frontend
engrammar search "testing" --category development/testing
```

**By Tags:**
```bash
# Single tag
engrammar search "component" --tags react

# Multiple tags (AND)
engrammar search "ui" --tags acme,react,picasso
```

**Combined:**
```bash
engrammar search "patterns" \
  --category development/frontend \
  --tags react,typescript
```

### Understanding Results

```
Results show:
- id: Lesson identifier
- score: Relevance (higher = better)
- category: Hierarchical category
- text: Lesson content
- matched: How many times shown and used
- occurrences: How many sessions mentioned this

High matched count = proven useful
```

---

## Common Workflows

### 1. Add Project-Specific Lesson

```bash
# Detect current environment
engrammar detect-tags

# Add lesson with detected tags
engrammar add "Use Picasso table components for data tables" \
  --category development/frontend/components \
  --tags acme,react,picasso,frontend
```

### 2. Search Before Implementation

```bash
# Starting new feature
engrammar search "form validation patterns" --tags react

# Before using a tool
engrammar search "git workflow" --category development/git
```

### 3. Record Learning After Bug Fix

```python
# In Claude Code session after fixing bug
engrammar_add(
    text="Always validate API responses before state updates",
    category="development/frontend/errors",
    tags=["react", "typescript", "api"]
)
```

### 4. Mark Lesson as Not Applicable

```python
# Lesson showed but doesn't apply
engrammar_feedback(
    lesson_id=42,
    applicable=False,
    reason="This project doesn't use Figma",
    add_prerequisites={"mcp_servers": ["figma"]}
)
```

### 5. Update Lesson After Refactor

```bash
# Find lesson
engrammar search "old pattern name"

# Update it
engrammar update 42 \
  --text "New pattern: use hooks instead of HOCs" \
  --category development/frontend/patterns
```

### 6. Pin Critical Lesson

```bash
# Pin for all projects
engrammar pin 42

# Pin for specific environment
engrammar update 42 --prereqs '{"tags":["acme"]}'
engrammar pin 42
```

### 7. Clean Up Deprecated Lessons

```bash
# List all lessons
engrammar list

# Deprecate outdated ones
engrammar deprecate 42
engrammar deprecate 43

# Rebuild index (removes deprecated from search)
engrammar rebuild
```

### 8. Export for Backup

```bash
# Export to markdown
engrammar export > ~/backups/engrammar-$(date +%Y%m%d).md

# Export to JSON (manual query)
sqlite3 ~/.engrammar/lessons.db \
  "SELECT * FROM lessons WHERE deprecated = 0" \
  > ~/backups/lessons.json
```

### 9. Investigate Auto-Pin

```bash
# Check which lessons are pinned
engrammar list | grep PINNED

# Check tag stats for a lesson
sqlite3 ~/.engrammar/lessons.db \
  "SELECT * FROM lesson_tag_stats WHERE lesson_id = 42"
```

### 10. Debug Tag Detection

```bash
# See what tags are detected
cd ~/work/acme/app-repo
engrammar detect-tags

# Test search with tags
engrammar search "test" --tags frontend,react

# Check environment in status
engrammar status
```

---

## Quick Reference

### Most Common Commands

```bash
# See current environment
engrammar detect-tags

# Search
engrammar search "query" --tags tag1,tag2

# Add with tags
engrammar add "text" --category cat --tags tag1,tag2

# Status
engrammar status
```

### Most Common MCP Tools

```python
# Search in Claude Code
engrammar_search(query="pattern", tags=["react"])

# Add lesson
engrammar_add(text="lesson", category="cat", tags=["tag"])

# Give feedback
engrammar_feedback(lesson_id=42, applicable=False, reason="why")
```

### File Locations

```
~/.engrammar/
├── lessons.db              # SQLite database
├── embeddings.npy          # Vector search index
├── config.json             # Configuration
├── engrammar-cli           # CLI executable
└── .session-shown.json     # Current session tracking
```

### Config File

```json
{
  "hooks": {
    "prompt_enabled": true,      # Show at session start
    "tool_use_enabled": true,    # Show before tool use
    "skip_tools": ["Read", "Glob"]  # Don't show for these tools
  },
  "search": {
    "top_k": 5                   # Default result count
  },
  "display": {
    "max_lessons_per_tool": 2    # Max per tool use
  }
}
```

---

## Troubleshooting

### Tags Not Detected

```bash
# Check detection
engrammar detect-tags

# Verify files exist
ls -la tsconfig.json package.json Gemfile

# Check git remote
git remote -v
```

### Lesson Not Appearing

```bash
# Check prerequisites match
engrammar status  # See current tags

# Check lesson details
engrammar list | grep -A5 "lesson text"

# Verify not deprecated
sqlite3 ~/.engrammar/lessons.db \
  "SELECT * FROM lessons WHERE id = 42"
```

### Auto-Pin Not Working

```bash
# Check tag stats
sqlite3 ~/.engrammar/lessons.db \
  "SELECT * FROM lesson_tag_stats WHERE lesson_id = 42"

# Verify threshold (15 matches needed)
sqlite3 ~/.engrammar/lessons.db \
  "SELECT tag_set, SUM(times_matched) as total
   FROM lesson_tag_stats
   WHERE lesson_id = 42
   GROUP BY tag_set"
```

### Search Not Finding Results

```bash
# Rebuild index
engrammar rebuild

# Try broader query
engrammar search "single keyword"

# Check if lesson exists
engrammar list --category development
```

---

## Environment Variables

```bash
# Engrammar home directory
export ENGRAMMAR_HOME=~/.engrammar

# Anthropic API key (optional, for AI evaluation)
export ANTHROPIC_API_KEY=sk-...
```

---

## Tips & Tricks

### 1. Use Specific Categories

```
Good:  development/frontend/hooks
Bad:   development/frontend
```

### 2. Tag Broadly

```
Good:  ["acme", "react", "frontend", "picasso"]
Bad:   ["acme"]
```

### 3. Write Actionable Lessons

```
Good:  "Use Picasso Table component instead of custom tables"
Bad:   "Tables are important"
```

### 4. Search Before Adding

```bash
# Avoid duplicates
engrammar search "similar concept"

# Then add if unique
engrammar add "new lesson"
```

### 5. Give Feedback

```python
# Help system learn
engrammar_feedback(
    lesson_id=42,
    applicable=False,
    reason="Specific reason",
    add_prerequisites={"tags": ["relevant-tag"]}
)
```

### 6. Let Auto-Pin Work

Don't manually pin everything - let the 15-match threshold work naturally.

### 7. Use Tags for Context

Tags help the system understand when lessons apply:
- `["acme", "react"]` - Acme React projects
- `["personal", "vue"]` - Personal Vue projects
- `["backend", "rails"]` - Rails backend work

### 8. Monitor with Status

```bash
# Regular check-in
engrammar status

# See environment
engrammar detect-tags
```

---

## Advanced

### Custom Tag Patterns

Edit `~/.engrammar/engrammar/tag_patterns.py`:

```python
# Add custom path pattern
PATH_PATTERNS.append(
    (re.compile(r"/work/myproject/"), "myproject")
)

# Add custom dependency
PACKAGE_DEPENDENCY_TAGS["my-library"] = ["mylibrary", "frontend"]
```

### Database Queries

```bash
# Most matched lessons
sqlite3 ~/.engrammar/lessons.db \
  "SELECT id, text, times_matched
   FROM lessons
   WHERE deprecated = 0
   ORDER BY times_matched DESC
   LIMIT 10"

# Tag distribution
sqlite3 ~/.engrammar/lessons.db \
  "SELECT tag_set, COUNT(*) as lessons, SUM(times_matched) as matches
   FROM lesson_tag_stats
   GROUP BY tag_set
   ORDER BY matches DESC"

# Pinned lessons
sqlite3 ~/.engrammar/lessons.db \
  "SELECT id, text, prerequisites
   FROM lessons
   WHERE pinned = 1 AND deprecated = 0"
```

### Batch Operations

```bash
# Bulk add from file
while IFS= read -r line; do
  engrammar add "$line" --category bulk --tags imported
done < lessons.txt

# Bulk deprecate old lessons
sqlite3 ~/.engrammar/lessons.db \
  "UPDATE lessons
   SET deprecated = 1
   WHERE created_at < '2024-01-01'"
```

---

## Quick Start Examples

### Example 1: New Frontend Project

```bash
cd ~/work/myproject
engrammar detect-tags
# Tags: frontend, react, typescript

engrammar search "component patterns"
engrammar search "state management"
engrammar search "testing"
```

### Example 2: Record Bug Fix

```python
# After fixing authentication bug
engrammar_add(
    text="Always check token expiry before API calls",
    category="development/backend/auth",
    tags=["backend", "api", "auth"]
)
```

### Example 3: Setup New Machine

```bash
# Clone or install engrammar
cd ~/.engrammar
./engrammar-cli setup

# Import previous lessons (if backed up)
./engrammar-cli import ~/backups/lessons.json

# Verify
./engrammar-cli status
```

---

## Performance Tips

### Fast Operations

- ✅ Search: ~100ms
- ✅ Add: ~50ms
- ✅ Tag detection: ~30ms
- ✅ Status: ~10ms

### Slow Operations

- ⚠️ First index build: ~30s (1000 lessons)
- ⚠️ Rebuild: ~30s
- ⚠️ Export: ~5s (large datasets)

### Optimization

```bash
# Don't rebuild unnecessarily
# Only after bulk adds/updates

# Use pagination for large lists
engrammar list --limit 20 --offset 0

# Filter searches
engrammar search "query" --tags specific
```

---

## See Also

- [README.md](../README.md) - Overview and features
- [ARCHITECTURE.md](ARCHITECTURE.md) - Technical deep dive
- [GitHub Issues](https://github.com/anthropics/engrammar/issues) - Report bugs

---

## Version

This cheatsheet is for **Engrammar with Tag System v1.0**

Last updated: 2026-02-17
