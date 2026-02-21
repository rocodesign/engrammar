# Engrammar CLI

The Engrammar CLI provides command-line access to all engram management operations, matching the functionality available through MCP tools.

## Installation

After running `bash setup.sh`, the CLI is available at:

```bash
~/.engrammar/engrammar-cli
```

### Adding to PATH (optional)

For convenient access from anywhere, add to your `~/.zshrc` or `~/.bashrc`:

```bash
export PATH="$HOME/.engrammar:$PATH"
alias engrammar="$HOME/.engrammar/engrammar-cli"
```

Then reload: `source ~/.zshrc`

Now you can use: `engrammar status` instead of the full path.

## Commands

### Setup & Status

#### `setup`

Initialize database, import existing engrams, and build embedding index.

```bash
engrammar setup
```

#### `status`

Show database stats, index health, and hook configuration.

```bash
engrammar status
```

**Output:**

- Database path and engram count
- Category breakdown
- Embedding index status
- Hook configuration (enabled/disabled, skip tools)

### Search & Browse

#### `search`

Search engrams using hybrid search (vector + BM25).

```bash
engrammar search "inline styles"
engrammar search "figma" --category tools
```

**Options:**

- `--category CATEGORY` - Filter by category prefix

**Output:**

- Ranked results with scores
- Match count and occurrence count per engram

#### `list`

List all active engrams with pagination.

```bash
engrammar list
engrammar list --offset 20 --limit 10
engrammar list --category development/frontend
```

**Options:**

- `--offset N` - Skip first N engrams (default: 0)
- `--limit N` - Show N engrams (default: 20)
- `--category CATEGORY` - Filter by category

**Output:**

- Engram ID, category, and text preview
- Pin status (📌 if pinned)
- Prerequisites (if set)
- Match stats

### Add & Update

#### `add`

Add a new engram.

```bash
engrammar add "Never use inline styles in React components" --category development/frontend/styling
```

**Options:**

- `--category CATEGORY` - Set engram category (default: "general")

**Behavior:**

- Automatically rebuilds embedding index
- Sets source to "manual"

#### `update`

Update a engram's text, category, or prerequisites.

```bash
engrammar update 42 --text "Updated engram text"
engrammar update 42 --category tools/figma
engrammar update 42 --prereqs '{"repos": ["app-repo"]}'
```

**Options:**

- `--text "new text"` - Update engram text
- `--category CATEGORY` - Update primary category
- `--prereqs JSON` - Update prerequisites (JSON string)

**Behavior:**

- Syncs junction table when category changes
- Rebuilds embedding index if text changed

#### `deprecate`

Soft-delete a engram (removes from active engrams, keeps in DB).

```bash
engrammar deprecate 42
```

### Categories

#### `categorize`

Add or remove categories from a engram (multi-category support).

```bash
engrammar categorize 42 add development/frontend
engrammar categorize 42 remove tools/figma
```

**Usage:**

- `categorize LESSON_ID add CATEGORY` - Add category to engram
- `categorize LESSON_ID remove CATEGORY` - Remove category from engram

### Pinning

#### `pin`

Pin a engram (always shown at session start when prerequisites match).

```bash
engrammar pin 42
```

#### `unpin`

Unpin a engram.

```bash
engrammar unpin 42
```

### Import & Export

#### `import`

Import engrams from a JSON or markdown file.

```bash
engrammar import engrams.json
engrammar import engrams.md
```

**Formats:**

- **JSON**: Array of objects with `engram`, `topic`, `source_sessions` fields
- **Markdown**: Each line starting with `- ` is imported as a engram

**Behavior:**

- Automatically rebuilds embedding index after import

#### `export`

Export all active engrams to markdown, grouped by category.

```bash
engrammar export > engrams.md
```

**Output format:**

```markdown
## development/frontend

- Never use inline styles in React components
- Always use CSS modules for component styling

## tools/figma

- Use Figma MCP server to fetch design tokens
```

### Maintenance

#### `extract`

Extract engrams from Claude Code session facets (hook friction events).

```bash
engrammar extract
engrammar extract --dry-run
```

**Options:**

- `--dry-run` - Show what would be extracted without saving

**Behavior:**

- Scans `~/.claude/projects/` for session facets
- Extracts friction events (hook failures, errors, corrections)
- Deduplicates and merges similar engrams
- Runs automatically at session start via hook

#### `rebuild`

Rebuild the embedding index from scratch.

```bash
engrammar rebuild
```

**Use when:**

- After manual database changes
- After bulk imports
- If index becomes corrupted

## Examples

### Daily Workflow

```bash
# Check system status
engrammar status

# Search for engrams about a topic
engrammar search "react hooks"

# Browse recent engrams
engrammar list --limit 10

# Add a new engram from experience
engrammar add "Always use useCallback for event handlers in memoized components" --category development/frontend/react

# Pin a critical engram
engrammar pin 15

# Update prerequisites for a repo-specific engram
engrammar update 23 --prereqs '{"repos": ["app-repo"], "mcp_servers": ["figma"]}'
```

### Maintenance

```bash
# Export engrams for backup
engrammar export > backup-$(date +%Y%m%d).md

# Import engrams from another system
engrammar import external-engrams.json

# Rebuild index after manual DB work
engrammar rebuild

# Extract engrams from recent sessions
engrammar extract
```

### Multi-Category Management

```bash
# Add engram with primary category
engrammar add "Use Figma tokens for spacing" --category design

# Add additional categories
engrammar categorize 50 add development/frontend
engrammar categorize 50 add tools/figma

# List engrams in a category
engrammar list --category tools/figma
```

## Environment Variables

- `ENGRAMMAR_HOME` - Override installation directory (default: `~/.engrammar`)

## Exit Codes

- `0` - Success
- `1` - Error (missing files, invalid arguments, database errors)

## See Also

- [README.md](../README.md) - System overview and architecture
- [config.json](../.engrammar/config.json) - Configuration reference
