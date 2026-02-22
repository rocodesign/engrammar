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

Initialize database, import existing engrams, and build embedding index (both content and tag embeddings).

```bash
engrammar setup
```

#### `status`

Show database stats, index health, tag index status, and hook configuration.

```bash
engrammar status
```

**Output:**

- Database path and engram count
- Category breakdown
- Embedding index status (vector count and dimensions)
- Tag index status (cached tag embeddings)
- Hook configuration (enabled/disabled, skip tools)

#### `detect-tags`

Show the environment tags detected for the current directory.

```bash
engrammar detect-tags
```

**Output:**

- Detected tags (from paths, git, files, deps, directory structure)
- Current directory
- Repository name

### Search & Browse

#### `search`

Search engrams using hybrid search (vector + BM25).

```bash
engrammar search "inline styles"
engrammar search "figma" --category tools
engrammar search "state management" --tags react
engrammar search "ui component" --tags acme,react,frontend
```

**Options:**

- `--category CATEGORY` - Filter by category prefix
- `--tags tag1,tag2,...` - Filter by required tags (AND logic)

**Output:**

- Ranked results with scores
- Match count and occurrence count per engram

#### `list`

List all active engrams with pagination.

```bash
engrammar list
engrammar list --offset 20 --limit 10
engrammar list --category development/frontend
engrammar list --verbose --sort score
engrammar list -v --sort matched
```

**Options:**

- `--offset N` - Skip first N engrams (default: 0)
- `--limit N` - Show N engrams (default: 20)
- `--category CATEGORY` - Filter by category
- `--verbose` / `-v` - Show full details: per-tag relevance scores, repo stats, prerequisites, source transcripts (git-log style)
- `--sort id|score|matched` - Sort order (default: `id`). `score` sorts by best tag relevance score, `matched` by times_matched

**Output (default):**

- Engram ID, category, and text preview
- Pin status, prerequisites, match stats

**Output (verbose):**

- Full engram text, category, source, creation/update dates
- Per-tag relevance scores with color coding (green positive, red negative)
- Per-repo match statistics
- Source transcript paths

#### `log`

Show the hook event log — what was injected, when, and by which hook.

```bash
engrammar log
engrammar log --tail 50
engrammar log --session abc12345
engrammar log --hook UserPromptSubmit
```

**Options:**

- `--tail N` - Number of events to show (default: 20)
- `--session ID` - Filter by session ID prefix
- `--hook HOOK` - Filter by hook name (SessionStart, UserPromptSubmit, PreToolUse)

**Output:**

- Timestamp, hook event name, session ID
- Injected engram IDs with text snippets
- Context (query or tool name)

### Add & Update

#### `add`

Add a new engram.

```bash
engrammar add "Never use inline styles in React components" --category development/frontend/styling
engrammar add "Follow acme's React patterns" --category development/frontend --tags acme,react,frontend
```

**Options:**

- `--category CATEGORY` - Set engram category (default: "general")
- `--tags tag1,tag2,...` - Set environment tags (stored as prerequisites)

**Behavior:**

- Automatically rebuilds embedding and tag indexes
- Sets source to "manual"

#### `update`

Update a engram's text, category, or prerequisites.

```bash
engrammar update ENGRAM_ID --text "Updated engram text"
engrammar update ENGRAM_ID --category tools/figma
engrammar update ENGRAM_ID --prereqs '{"repos": ["app-repo"]}'
```

**Options:**

- `--text "new text"` - Update engram text
- `--category CATEGORY` - Update primary category
- `--prereqs JSON` - Update prerequisites (JSON string)

**Behavior:**

- Syncs junction table when category changes
- Rebuilds embedding index if text changed
- Rebuilds tag index if prerequisites changed

#### `deprecate`

Soft-delete a engram (removes from active engrams, keeps in DB).

```bash
engrammar deprecate ENGRAM_ID
```

### Categories

#### `categorize`

Add or remove categories from a engram (multi-category support).

```bash
engrammar categorize ENGRAM_ID add development/frontend
engrammar categorize ENGRAM_ID remove tools/figma
```

**Usage:**

- `categorize ENGRAM_ID add CATEGORY` - Add category to engram
- `categorize ENGRAM_ID remove CATEGORY` - Remove category from engram

### Pinning

#### `pin`

Pin a engram (always shown at session start when prerequisites match).

```bash
engrammar pin ENGRAM_ID
```

#### `unpin`

Unpin a engram.

```bash
engrammar unpin ENGRAM_ID
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

- Automatically rebuilds embedding and tag indexes after import

#### `export`

Export all active engrams to markdown, grouped by category.

```bash
engrammar export > engrams.md
```

### Extraction & Evaluation

#### `extract`

Extract engrams from Claude Code session transcripts.

```bash
engrammar extract
engrammar extract --limit 20
engrammar extract --session UUID
engrammar extract --dry-run
engrammar extract --facets
```

**Options:**

- `--limit N` - Process at most N transcripts
- `--session UUID` - Extract from a single session
- `--dry-run` - Show what would be extracted without saving
- `--facets` - Use facet-based extraction pipeline instead of transcript-based

**Behavior:**

- Scans `~/.claude/projects/` for session transcripts
- Sends conversation to Haiku for friction analysis
- Deduplicates and merges similar engrams
- Rebuilds index after extraction

#### `evaluate`

Run relevance evaluations for pending sessions or a specific session.

```bash
engrammar evaluate
engrammar evaluate --limit 10
engrammar evaluate --session UUID
```

**Options:**

- `--limit N` - Process at most N sessions (default: 5)
- `--session UUID` - Evaluate a specific session

**Behavior:**

- Reads transcript + shown engrams from session_audit
- Haiku judges per-engram relevance
- Updates tag relevance scores via EMA

#### `backfill`

Create audit records from past sessions for the evaluator pipeline.

```bash
engrammar backfill
engrammar backfill --dry-run
engrammar backfill --limit 50
engrammar backfill --evaluate
```

Delegates to `backfill_stats.py` — all arguments are forwarded.

#### `backfill-prereqs`

Retroactively set prerequisites on existing engrams using keyword inference + session audit tags.

```bash
engrammar backfill-prereqs
engrammar backfill-prereqs --dry-run
```

**Options:**

- `--dry-run` - Show what would be changed without saving

**Behavior:**

- Infers prerequisites from engram text keywords
- Enriches with tags from session audit records
- Rebuilds tag index after updates

### Maintenance

#### `rebuild`

Rebuild embedding index (content + tag embeddings) from scratch.

```bash
engrammar rebuild
```

**Use when:**

- After manual database changes
- After bulk imports
- If index becomes corrupted

#### `reset-stats`

Reset all match statistics and pins to start fresh.

```bash
engrammar reset-stats --confirm
```

**Requires `--confirm` flag.** Resets:

- Unpins all engrams
- Resets times_matched to 0
- Clears per-repo match tracking
- Preserves engram text, categories, and manual prerequisites

#### `restore`

List database backups and restore a selected one.

```bash
engrammar restore --list    # List available backups
engrammar restore           # Interactive selection
engrammar restore 2         # Restore backup #2
```

Looks for `engrams.db.backup-*` files in `~/.engrammar/`.

## Environment Variables

- `ENGRAMMAR_HOME` - Override installation directory (default: `~/.engrammar`)

## Exit Codes

- `0` - Success
- `1` - Error (missing files, invalid arguments, database errors)

## See Also

- [README.md](../README.md) - System overview
- [ARCHITECTURE.md](ARCHITECTURE.md) - Technical internals
- [CHEATSHEET.md](CHEATSHEET.md) - Quick reference
