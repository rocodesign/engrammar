# Engrammar Matching Cheat Sheet

This guide explains how lesson matching works with categories, repos, paths, and other prerequisites.

## Mental model

Matching happens in two stages:

1. Prerequisite gate (hard filter)
- A lesson is eligible only if all prerequisite fields pass.
- If a prerequisite field fails, the lesson is excluded before ranking.

2. Relevance ranking (vector + BM25)
- Only eligible lessons are ranked for the current prompt/tool context.

## What each field does

- `category`
  - Organizational label for lessons.
  - Helps with browsing and optional category-filtered search.
  - Does not scope by repo/path on its own.

- `prerequisites.repos`
  - Restricts lessons to one or more repository names.
  - Good for project-specific conventions.

- `prerequisites.paths`
  - Restricts lessons by current working directory prefix.
  - Good for monorepos, workspace areas, or client folders.

- `prerequisites.os`
  - Restricts lessons to specific OS values (`darwin`, `linux`, `windows`).

- `prerequisites.mcp_servers`
  - Requires listed MCP servers to be configured/available.

## Example runtime environment

Assume the current environment is:

```json
{
  "repo": "web-portal",
  "cwd": "/Users/dev/work/clients/atlas/web-portal/apps/admin",
  "os": "darwin",
  "mcp_servers": ["engrammar", "figma"]
}
```

## Matching examples

1. Global lesson

```json
{
  "category": "development/frontend",
  "prerequisites": null
}
```

- Match: Yes
- Why: No prerequisites, so it is eligible everywhere.

2. Repo-scoped lesson

```json
{
  "category": "development/git",
  "prerequisites": { "repos": ["web-portal"] }
}
```

- Match: Yes
- Why: `repo` matches exactly.

3. Repo mismatch

```json
{
  "category": "development/git",
  "prerequisites": { "repos": ["billing-service"] }
}
```

- Match: No
- Why: Current repo is `web-portal`.

4. Path-scoped lesson

```json
{
  "category": "workflow/setup",
  "prerequisites": { "paths": ["~/work/clients/atlas/web-portal"] }
}
```

- Match: Yes
- Why: Current cwd starts with expanded path.

5. Path mismatch

```json
{
  "category": "workflow/setup",
  "prerequisites": { "paths": ["~/work/clients/zephyr/mobile-app"] }
}
```

- Match: No
- Why: Current cwd does not start with that path.

6. Repo AND path (strict project targeting)

```json
{
  "category": "tools/figma",
  "prerequisites": {
    "repos": ["web-portal"],
    "paths": ["~/work/clients/atlas/web-portal/apps/admin"]
  }
}
```

- Match: Yes
- Why: Both repo and path pass.

7. OS + MCP requirement

```json
{
  "category": "tools/figma",
  "prerequisites": {
    "os": ["darwin"],
    "mcp_servers": ["figma"]
  }
}
```

- Match: Yes
- Why: Running on macOS and `figma` MCP server is available.

8. OS mismatch

```json
{
  "category": "tools/figma",
  "prerequisites": {
    "os": ["linux"],
    "mcp_servers": ["figma"]
  }
}
```

- Match: No
- Why: OS fails, even though MCP server is available.

9. Category-only lesson (common misunderstanding)

```json
{
  "category": "client/atlas/web",
  "prerequisites": null
}
```

- Match: Yes (globally)
- Why: Category text does not enforce scoping.
- Note: It is only scoping if you add `repos`/`paths` prerequisites.

## Category combinations

A lesson can have one primary category and additional categories.

Example:

```json
{
  "category": "development/frontend/forms",
  "additional_categories": ["quality/accessibility", "tools/storybook"]
}
```

- It can be found by explicit category filters against any of those categories.
- This still does not replace prerequisites for repo/path scoping.

## Recommended patterns

- Cross-project best practice
  - Use category only, no prerequisites.

- Project-specific rule
  - Use `repos`.

- Subtree-specific rule (monorepo/client folder)
  - Use `paths`.

- Very strict scoping
  - Use `repos` + `paths` together.

- Tool-availability rule
  - Use `mcp_servers` (optionally with `os`).

## Quick templates

Project-specific template:

```json
{
  "repos": ["web-portal"]
}
```

Folder-specific template:

```json
{
  "paths": ["~/work/clients/atlas/web-portal/apps/admin"]
}
```

Strict template:

```json
{
  "repos": ["web-portal"],
  "paths": ["~/work/clients/atlas/web-portal/apps/admin"],
  "os": ["darwin"],
  "mcp_servers": ["figma"]
}
```
