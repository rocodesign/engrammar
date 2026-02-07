# Semantic Lesson Search System -- Architecture

## 1. Component Diagram

```
+---------------------------+
|     Claude Code CLI       |
|  (UserPromptSubmit hook)  |
+----------+----------------+
           | HTTP POST (user prompt)
           v
+----------+----------------+
|   Lesson Search Server    |
|   (FastAPI, persistent)   |
|                           |
|  +---------------------+ |
|  | Ollama Client        | |   HTTP /api/embed
|  | (httpx, async)       +-------> Ollama (resident daemon)
|  +---------------------+ |        nomic-embed-text v1.5
|                           |        port 11434
|  +---------------------+ |
|  | ChromaDB             | |
|  | (in-process, HNSW)   | |
|  | ~/.local/share/      | |
|  |   lesson-search/db/  | |
|  +---------------------+ |
|                           |
|  +---------------------+ |
|  | Category Classifier  | |
|  | (keyword + embedding | |
|  |  hybrid approach)    | |
|  +---------------------+ |
+---------------------------+
        port 7731
```

### Components

| Component | Role | Lifecycle |
|-----------|------|-----------|
| **Lesson Search Server** | FastAPI process; receives queries, returns ranked lessons | Persistent via launchd LaunchAgent |
| **Ollama** | Embedding generation; stays resident in background | Persistent via its own launchd LaunchAgent (ships with Ollama.app install) |
| **ChromaDB** | In-process vector store with HNSW index; persisted to disk | Loaded inside the FastAPI process; no separate daemon |
| **UserPromptSubmit Hook** | Shell script triggered by Claude Code on every user prompt | Ephemeral; runs per-prompt, exits immediately |
| **CLI Ingest Tool** | Command-line utility for adding/updating/bulk-importing lessons | On-demand; invoked manually or via cron |

## 2. Data Flow

### 2.1 Lesson Ingestion

```
lessons.md / individual files
        |
        v
  $ lesson-search ingest <file-or-stdin>
        |
        v
  Parse into records:
    { id, text, categories[], source_file, created_at }
        |
        v
  POST /api/ingest  -->  Server
        |
        +---> Ollama /api/embed  -->  embedding vector (768d)
        |
        +---> Category classifier  -->  resolved categories[]
        |
        v
  ChromaDB collection.upsert(
    id, embedding, document=text,
    metadata={ categories, source_file, created_at }
  )
```

**Ingestion flow detail:**

1. The CLI tool reads a markdown file (or stdin), splits it into lesson records using a `## Lesson:` delimiter (or YAML frontmatter).
2. Each record is sent to `POST /api/ingest` with its raw text and optional user-supplied categories.
3. The server calls Ollama to generate the embedding.
4. If categories are not supplied, the server's category classifier assigns them (see Section 5).
5. The record is upserted into ChromaDB with the embedding, full text, and metadata.

### 2.2 Query (on every user prompt)

```
User types prompt in Claude Code
        |
        v
  UserPromptSubmit hook fires
        |
        v
  Hook script (curl or Python):
    POST /api/query
    { "prompt": "<user's message>", "top_k": 5, "categories": null }
        |
        v
  Server:
    1. Embed the prompt via Ollama       (~15-25ms)
    2. ChromaDB.query(embedding, top_k)  (~2-5ms)
    3. Format results as context block    (~<1ms)
        |
        v
  Return JSON:
    { "lessons": [ { "text": "...", "score": 0.87, "categories": [...] } ] }
        |
        v
  Hook script prints to stdout:
    "## Relevant Lessons\n- lesson 1\n- lesson 2"
        |
        v
  Claude Code injects stdout as context
  Claude sees the lessons alongside the user's prompt
```

**Latency budget (target <50ms total):**

| Step | Target | Notes |
|------|--------|-------|
| Hook script startup | ~5ms | Compiled Go binary or lightweight Python with persistent connection |
| HTTP to local server | ~1ms | localhost, keep-alive |
| Ollama embedding | ~15-25ms | nomic-embed-text, model already loaded in VRAM/unified memory |
| ChromaDB query | ~2-5ms | HNSW in-memory index, <10K vectors |
| Response formatting | ~1ms | String concatenation |
| **Total** | **~24-37ms** | Well within 50ms budget |

## 3. API Contract

### 3.1 `POST /api/query`

Query for relevant lessons given a user prompt.

**Request:**
```json
{
  "prompt": "How do I fix the failing CI pipeline for the frontend build?",
  "top_k": 5,
  "categories": ["devops/ci-cd", "development/frontend"],
  "min_score": 0.5
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | yes | -- | The user's raw prompt text |
| `top_k` | int | no | 5 | Max number of lessons to return |
| `categories` | string[] | no | null | Filter to these category prefixes (hierarchical match) |
| `min_score` | float | no | 0.4 | Minimum cosine similarity threshold |

**Response (200):**
```json
{
  "lessons": [
    {
      "id": "lesson-042",
      "text": "When the frontend CI build fails with ENOMEM, increase the Node heap size via NODE_OPTIONS=--max-old-space-size=4096 in the CI env.",
      "score": 0.89,
      "categories": ["devops/ci-cd", "development/frontend/build"],
      "source_file": "lessons/ci-fixes.md",
      "created_at": "2025-11-15T10:30:00Z"
    }
  ],
  "query_time_ms": 28,
  "model": "nomic-embed-text:v1.5"
}
```

### 3.2 `POST /api/ingest`

Add or update a lesson.

**Request:**
```json
{
  "id": "lesson-042",
  "text": "When the frontend CI build fails with ENOMEM...",
  "categories": ["devops/ci-cd", "development/frontend/build"],
  "source_file": "lessons/ci-fixes.md"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | no | Auto-generated UUID if omitted; used for upsert |
| `text` | string | yes | The lesson content |
| `categories` | string[] | no | If omitted, auto-classified by the server |
| `source_file` | string | no | Provenance tracking |

**Response (200):**
```json
{
  "id": "lesson-042",
  "categories": ["devops/ci-cd", "development/frontend/build"],
  "status": "upserted"
}
```

### 3.3 `POST /api/ingest/bulk`

Bulk import from a structured file.

**Request:**
```json
{
  "lessons": [
    { "text": "...", "categories": ["..."] },
    { "text": "...", "categories": ["..."] }
  ]
}
```

**Response (200):**
```json
{
  "ingested": 47,
  "errors": 0
}
```

### 3.4 `GET /api/health`

Health check for the server, Ollama, and ChromaDB.

**Response (200):**
```json
{
  "status": "healthy",
  "ollama": "connected",
  "chromadb_collections": 1,
  "lesson_count": 847,
  "model": "nomic-embed-text:v1.5",
  "uptime_seconds": 86400
}
```

### 3.5 `GET /api/categories`

List all categories with lesson counts.

**Response (200):**
```json
{
  "categories": {
    "development": 120,
    "development/frontend": 45,
    "development/frontend/styling": 12,
    "development/frontend/build": 8,
    "development/backend": 30,
    "devops/ci-cd": 22,
    "product-management/jira": 15,
    "acme/conventions": 18
  }
}
```

### 3.6 `DELETE /api/lessons/{id}`

Remove a lesson.

### 3.7 `PUT /api/lessons/{id}`

Update a lesson's text or categories (re-embeds automatically).

## 4. Claude Code Hook Integration

### 4.1 Hook Configuration

Add to `~/.claude/settings.json` (user-level, applies to all projects):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.local/bin/lesson-search-hook",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

### 4.2 Hook Script (`~/.local/bin/lesson-search-hook`)

```bash
#!/bin/bash
# Reads the prompt from stdin JSON, queries the lesson server,
# prints relevant lessons to stdout (injected as Claude context).

set -euo pipefail

# Parse the user's prompt from the hook input JSON
INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')

# Skip empty prompts or very short ones (likely commands)
if [ -z "$PROMPT" ] || [ ${#PROMPT} -lt 10 ]; then
  exit 0
fi

# Query the lesson search server (timeout 2s to stay within budget)
RESPONSE=$(curl -s --max-time 2 \
  -X POST http://127.0.0.1:7731/api/query \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": $(echo "$PROMPT" | jq -Rs .), \"top_k\": 3, \"min_score\": 0.55}" \
  2>/dev/null) || exit 0

# Extract lessons; if none found, exit silently
LESSON_COUNT=$(echo "$RESPONSE" | jq -r '.lessons | length' 2>/dev/null) || exit 0
if [ "$LESSON_COUNT" = "0" ] || [ "$LESSON_COUNT" = "null" ]; then
  exit 0
fi

# Format lessons as context for Claude
echo "## Relevant Lessons from Past Experience"
echo ""
echo "$RESPONSE" | jq -r '.lessons[] | "- **[\(.categories | join(", "))]** (relevance: \(.score | . * 100 | floor)%): \(.text)"'

exit 0
```

**Key design decisions for the hook:**

- **Timeout of 5 seconds** in the hook config (generous), but the curl call has a 2-second hard timeout. If the server is down, curl fails silently and the hook exits 0 (no context injected, no error shown to user).
- **`min_score: 0.55`** prevents low-quality matches from cluttering context.
- **`top_k: 3`** keeps injected context concise. More lessons = more tokens consumed from Claude's context window.
- **Silent failure**: if anything goes wrong (server down, Ollama down, parse error), the hook exits 0 with no output. The user experience is unaffected.

### 4.3 Alternative: Python Hook Script (faster startup with persistent connection)

For lower latency, use a compiled hook or a Python script with `httpx`:

```python
#!/usr/bin/env python3
"""lesson-search-hook: Query lesson server on each user prompt."""
import sys, json, urllib.request

def main():
    input_data = json.load(sys.stdin)
    prompt = input_data.get("prompt", "")
    if len(prompt) < 10:
        return

    try:
        req = urllib.request.Request(
            "http://127.0.0.1:7731/api/query",
            data=json.dumps({"prompt": prompt, "top_k": 3, "min_score": 0.55}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
    except Exception:
        return  # Silent failure

    lessons = data.get("lessons", [])
    if not lessons:
        return

    print("## Relevant Lessons from Past Experience\n")
    for lesson in lessons:
        cats = ", ".join(lesson.get("categories", []))
        score = int(lesson.get("score", 0) * 100)
        print(f"- **[{cats}]** (relevance: {score}%): {lesson['text']}")

if __name__ == "__main__":
    main()
```

## 5. Hierarchical Categories

### 5.1 Category Taxonomy

Categories form a tree. Every lesson has one or more category paths. Queries can filter by prefix to narrow scope.

```
development/
  frontend/
    styling
    build
    testing
    react
    typescript
  backend/
    api
    database
    authentication
  tooling/
    git
    ide
    linting
product-management/
  jira
  requirements
  estimation
devops/
  ci-cd
  docker
  deployment
  monitoring
acme/
  conventions
  onboarding
  team-processes
workflow/
  claude-code
  debugging
  code-review
```

### 5.2 Storage in ChromaDB

Categories are stored as metadata on each ChromaDB document:

```python
collection.upsert(
    ids=["lesson-042"],
    embeddings=[embedding_vector],
    documents=["When the frontend CI build fails..."],
    metadatas=[{
        "categories": "devops/ci-cd,development/frontend/build",
        "category_l0": "devops,development",
        "category_l1": "devops/ci-cd,development/frontend",
        "category_l2": "devops/ci-cd,development/frontend/build",
        "source_file": "lessons/ci-fixes.md",
        "created_at": "2025-11-15T10:30:00Z"
    }]
)
```

**Why denormalized level fields?** ChromaDB metadata filtering uses `$contains` on strings. Storing each hierarchy level separately allows efficient prefix matching:

```python
# Find all "development/frontend/*" lessons:
collection.query(
    query_embeddings=[prompt_embedding],
    where={"category_l1": {"$contains": "development/frontend"}},
    n_results=5
)
```

### 5.3 Category Classification

When a lesson is ingested without explicit categories, the server classifies it using a **hybrid approach**:

1. **Keyword matching (fast, first pass):** A dictionary maps keywords/phrases to categories. Example: "CI", "pipeline", "GitHub Actions" -> `devops/ci-cd`. This catches ~70% of lessons with high confidence.

2. **Embedding similarity to category exemplars (second pass):** Pre-compute a centroid embedding for each category from its existing lessons. Compare the new lesson's embedding to each centroid. Assign categories where similarity exceeds a threshold (e.g., 0.6).

3. **No LLM required for classification.** This avoids adding latency or cost. If classification confidence is low, the lesson is tagged with the broadest matching category (e.g., `development/` instead of `development/frontend/styling`).

### 5.4 Category Filtering in Queries

The query API supports category filtering as optional narrowing. When `categories` is provided in the query, ChromaDB's `where` clause restricts the vector search to matching documents first, then ranks by embedding similarity.

When no categories are provided, the full collection is searched. This is the common case for the UserPromptSubmit hook, since we do not know in advance what category the user's prompt relates to.

## 6. Extension for Skill Discovery

The same architecture supports matching user prompts to relevant skills (Claude Code slash commands, custom tools, MCP servers, etc.).

### 6.1 Parallel Collection

```python
# Lessons collection (existing)
chroma_client.get_or_create_collection("lessons")

# Skills collection (new, same architecture)
chroma_client.get_or_create_collection("skills")
```

### 6.2 Skill Records

```json
{
  "id": "skill-review-pr",
  "text": "Review a GitHub pull request. Fetches PR diff, analyzes code changes, checks for issues, and posts review comments. Usage: /review-pr <number>",
  "categories": ["workflow/code-review", "development/tooling/git"],
  "metadata": {
    "skill_name": "review-pr",
    "trigger": "/review-pr",
    "source": "plugin:github-tools"
  }
}
```

### 6.3 Unified Query Endpoint

Extend `/api/query` with a `collections` parameter:

```json
{
  "prompt": "I need to review the PR that was just opened",
  "collections": ["lessons", "skills"],
  "top_k": 3
}
```

**Response:**
```json
{
  "results": {
    "lessons": [ { "text": "When reviewing PRs, always check..." } ],
    "skills": [ { "text": "Review a GitHub pull request...", "trigger": "/review-pr" } ]
  }
}
```

### 6.4 Hook Update

The hook script is updated to query both collections and format the output:

```
## Relevant Lessons
- [workflow/code-review] (92%): When reviewing PRs, always check for...

## Suggested Skills
- `/review-pr` - Review a GitHub pull request (89% match)
```

This requires zero architectural changes -- just a second ChromaDB collection and an extended query parameter.
