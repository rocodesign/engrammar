"""Engrammar MCP server — gives Claude direct access to engram management."""

import json
import os
import re
import sys

# Ensure engrammar package is importable
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "engrammar",
    instructions=(
        "Engrammar is your semantic knowledge system. Use it to search past engrams, "
        "add new learnings, mark engrams as not applicable, and check system status. "
        "Engrams from hooks appear in [ENGRAMMAR_V1] blocks with EG#ID markers "
        "(e.g. [EG#42]). When you notice a engram from hook context doesn't apply "
        "to the current environment, use engrammar_feedback to record why.\n\n"

        "## Proactive Engram Extraction\n\n"
        "You should actively extract engrams during sessions. Call engrammar_add "
        "(with source=\"self-extracted\") when any of these occur:\n"
        "- **User correction**: The user steers you away from an approach, tool, or pattern. "
        "Capture what was wrong AND the preferred alternative.\n"
        "- **Significant effort**: You spent multiple turns debugging, investigating, or "
        "iterating on something. Capture the root cause and fix so future sessions skip the struggle.\n"
        "- **Discovered convention**: You learn a project-specific pattern, naming convention, "
        "architecture rule, or workflow preference. Capture it as a reusable rule.\n"
        "- **Environment/tooling quirk**: A tool, API, or library behaves unexpectedly. "
        "Capture the gotcha and workaround.\n\n"

        "## Deduplication\n\n"
        "Before adding a engram, scan [ENGRAMMAR_V1] blocks already in your context — "
        "if a matching or partial engram exists, call engrammar_update to improve it instead "
        "of adding a duplicate. Do NOT call engrammar_search just to deduplicate; batch "
        "dedup runs separately.\n\n"

        "## Quality Criteria\n\n"
        "Only add engrams that are:\n"
        "- **Specific**: Contains concrete details (file paths, tool names, exact patterns), not vague advice.\n"
        "- **Actionable**: A future session can act on it without further context.\n"
        "- **Reusable**: Applies beyond this single session — would help in similar future situations.\n\n"

        "## Updating Injected Engrams\n\n"
        "When you see a engram in [ENGRAMMAR_V1] context that is incomplete, vague, or could be "
        "improved based on what you now know, call engrammar_update to refine it. "
        "Use the EG#ID to find the engram_id."
    ),
)


@mcp.tool()
def engrammar_search(query: str, category: str | None = None, tags: list[str] | None = None, top_k: int = 5) -> str:
    """Search engrams by semantic similarity + keyword matching.

    Use this to find relevant engrams for the current task.

    Args:
        query: Natural language search query
        category: Optional category prefix filter (e.g. "development/frontend")
        tags: Optional list of required tags (engrams must have ALL specified tags)
        top_k: Number of results to return (default 5)
    """
    from engrammar.search import search

    results = search(query, category_filter=category, tag_filter=tags, top_k=top_k)

    if not results:
        return "No matching engrams found."

    lines = [f"Found {len(results)} engrams:\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r.get('category', 'general')}] (id:{r['id']}, score:{r.get('score', 0):.4f})")
        lines.append(f"   {r['text']}")
        prereqs = r.get("prerequisites")
        if prereqs:
            lines.append(f"   prerequisites: {prereqs}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def engrammar_add(
    text: str,
    category: str = "general",
    tags: list[str] | None = None,
    prerequisites: dict | str | None = None,
    source: str = "manual",
) -> str:
    """Add a new engram to the knowledge base.

    Use this when you learn something that should be remembered across sessions.

    **Proactive usage — call this tool when you notice:**
    - A user correction (they steer you to a different approach, tool, or pattern)
    - Significant debugging effort (you spent multiple turns on something that had a non-obvious fix)
    - A project convention or preference that future sessions should know
    - A tooling/environment gotcha with a workaround

    **Before calling**, scan [ENGRAMMAR_V1] blocks in your context for duplicates.
    If a partial match exists, use engrammar_update to improve it instead.

    **Examples:**
    - User says "don't use relative imports here, use absolute" → add engram about import convention
    - You discover a test must run with specific env vars → add engram about test requirements
    - A library API changed and the old pattern fails → add engram about the new pattern

    Args:
        text: The engram text — what was learned. Be specific and actionable.
        category: Hierarchical category (e.g. "development/frontend/styling")
        tags: Optional list of environment tags (e.g. ["acme", "react", "frontend"])
        prerequisites: Optional requirements dict or JSON string (e.g. {"repos":["app-repo"],"os":["darwin"]})
        source: How this engram was discovered. Use "self-extracted" for engrams you
            proactively identify during a session. Other values: "manual" (user explicitly
            asked to save), "auto-extracted" (from facet pipeline), "feedback" (from feedback loop).
    """
    # Validate inputs
    if not text or not text.strip():
        return "Error: text cannot be empty."
    text = text.strip()

    if not category or not category.strip():
        return "Error: category cannot be empty."
    # Normalize category: strip slashes, collapse empty segments
    category = "/".join(seg for seg in category.strip("/").split("/") if seg)
    if not category:
        return "Error: category must contain at least one segment."

    from engrammar.db import add_engram, get_all_active_engrams
    from engrammar.embeddings import build_index

    # Auto-capture session_id from file written by SessionStart hook
    from engrammar.hook_utils import read_session_id
    session_id = read_session_id()
    source_sessions = []
    if session_id and _UUID_RE.match(session_id):
        source_sessions = [session_id]

    # Normalize prerequisites to dict
    prereqs_dict = {}

    if prerequisites:
        if isinstance(prerequisites, dict):
            prereqs_dict = prerequisites
        elif isinstance(prerequisites, str):
            try:
                prereqs_dict = json.loads(prerequisites)
            except json.JSONDecodeError:
                return f"Error: prerequisites must be valid JSON. Got: {prerequisites}"
        else:
            return f"Error: prerequisites must be dict or JSON string. Got: {type(prerequisites)}"

    # Merge tags into prerequisites
    if tags:
        prereqs_dict["tags"] = sorted(tags)

    engram_id = add_engram(
        text=text,
        category=category,
        source=source,
        source_sessions=source_sessions,
        prerequisites=prereqs_dict if prereqs_dict else None,
    )

    # Rebuild index
    engrams = get_all_active_engrams()
    build_index(engrams)

    return f"Added engram #{engram_id} in category '{category}'. Index rebuilt with {len(engrams)} engrams."


@mcp.tool()
def engrammar_deprecate(engram_id: int, reason: str = "") -> str:
    """Deprecate a engram that is no longer accurate or useful.

    Use this when a engram is outdated, wrong, or superseded.

    Args:
        engram_id: The engram ID to deprecate
        reason: Why this engram is being deprecated
    """
    from engrammar.db import deprecate_engram, get_connection, get_all_active_engrams
    from engrammar.embeddings import build_index

    # Verify engram exists
    conn = get_connection()
    row = conn.execute("SELECT text, category FROM engrams WHERE id = ?", (engram_id,)).fetchone()
    conn.close()

    if not row:
        return f"Error: engram #{engram_id} not found."

    deprecate_engram(engram_id)

    # Rebuild index without deprecated engram
    engrams = get_all_active_engrams()
    build_index(engrams)

    return f"Deprecated engram #{engram_id} [{row['category']}]: \"{row['text'][:80]}...\"\nReason: {reason}\nIndex rebuilt with {len(engrams)} active engrams."


@mcp.tool()
def engrammar_feedback(
    engram_id: int,
    applicable: bool,
    reason: str = "",
    tag_scores: dict | None = None,
    add_prerequisites: dict | str | None = None,
) -> str:
    """Give feedback on a engram that was surfaced by hooks.

    Use this when a engram from hook context doesn't apply to the current
    environment or situation. This helps Engrammar learn when to surface engrams.

    Args:
        engram_id: The engram ID (shown in hook context as [EG#N])
        applicable: Whether the engram was applicable in this context
        reason: Why the engram did/didn't apply (e.g. "requires figma MCP which isn't connected")
        tag_scores: Optional per-tag relevance scores (e.g. {"typescript": 0.9, "frontend": -0.3}).
            When provided, updates tag relevance with 2x weight. When omitted, derives
            weak signal from environment tags (+0.5 if applicable, -0.5 if not).
        add_prerequisites: Optional prerequisites dict or JSON string to add
            (e.g. {"mcp_servers":["figma"],"repos":["app-repo"]})
    """
    from engrammar.db import get_connection, update_tag_relevance
    from engrammar.environment import detect_environment
    from datetime import datetime

    conn = get_connection()
    row = conn.execute("SELECT text, category, prerequisites FROM engrams WHERE id = ?", (engram_id,)).fetchone()

    if not row:
        conn.close()
        return f"Error: engram #{engram_id} not found."

    now = datetime.utcnow().isoformat()
    response_parts = []

    if applicable:
        # Positive feedback — increment match count
        conn.execute(
            "UPDATE engrams SET times_matched = times_matched + 1, last_matched = ? WHERE id = ?",
            (now, engram_id),
        )
        response_parts.append(f"Recorded positive feedback for engram #{engram_id}.")
    else:
        # Negative feedback — record reason
        response_parts.append(f"Recorded negative feedback for engram #{engram_id}: {reason}")

    conn.commit()
    conn.close()

    # Update tag relevance scores
    if tag_scores:
        # Explicit tag scores from the model — high weight
        update_tag_relevance(engram_id, tag_scores, weight=2.0)
        response_parts.append(f"Updated tag relevance with explicit scores: {tag_scores}")
    else:
        # Derive weak signal from environment tags
        env = detect_environment()
        env_tags = env.get("tags", [])
        if env_tags:
            weak_score = 0.5 if applicable else -0.5
            derived_scores = {tag: weak_score for tag in env_tags}
            update_tag_relevance(engram_id, derived_scores, weight=1.0)
            response_parts.append(f"Updated tag relevance from env tags ({weak_score:+.1f})")

    # Add prerequisites if provided
    if add_prerequisites:
        conn = get_connection()
        # Normalize to dict
        if isinstance(add_prerequisites, str):
            try:
                new_prereqs = json.loads(add_prerequisites)
            except json.JSONDecodeError:
                response_parts.append(f"Warning: invalid prerequisites JSON, skipped: {add_prerequisites}")
                conn.close()
                return "\n".join(response_parts)
        elif isinstance(add_prerequisites, dict):
            new_prereqs = add_prerequisites
        else:
            response_parts.append(f"Warning: prerequisites must be dict or JSON string, skipped")
            conn.close()
            return "\n".join(response_parts)

        existing = {}
        if row["prerequisites"]:
            try:
                existing = json.loads(row["prerequisites"])
            except (json.JSONDecodeError, TypeError):
                pass

        # Merge: for list fields, union the values
        for key, val in new_prereqs.items():
            if key in existing:
                if isinstance(existing[key], list) and isinstance(val, list):
                    existing[key] = list(set(existing[key] + val))
                else:
                    existing[key] = val
            else:
                existing[key] = val

        conn.execute(
            "UPDATE engrams SET prerequisites = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing), now, engram_id),
        )
        response_parts.append(f"Updated prerequisites: {json.dumps(existing)}")
        conn.commit()
        conn.close()

    return "\n".join(response_parts)


@mcp.tool()
def engrammar_update(
    engram_id: int,
    text: str | None = None,
    category: str | None = None,
    prerequisites: dict | str | None = None,
) -> str:
    """Update an existing engram's text, category, or prerequisites.

    **When to use this instead of engrammar_add:**
    - You see a engram in [ENGRAMMAR_V1] context (marked as EG#ID) that is vague,
      incomplete, or could be improved with details you now have.
    - You found a near-duplicate via engrammar_search and want to enrich it rather
      than create a new engram.
    - A engram's category or prerequisites need correction based on current context.

    **Examples:**
    - An injected engram says "use absolute imports" but doesn't specify which project →
      update to add the repo prerequisite and more specific guidance.
    - A engram about a CLI flag is correct but missing the version where it changed →
      update the text to include the version.

    Args:
        engram_id: The engram ID to update (use EG#ID from [ENGRAMMAR_V1] blocks)
        text: New engram text (if changing)
        category: New category (if changing)
        prerequisites: New prerequisites dict or JSON string (if changing)
    """
    # Validate inputs
    if text is not None and not text.strip():
        return "Error: text cannot be empty."
    if category is not None:
        category = "/".join(seg for seg in category.strip("/").split("/") if seg)
        if not category:
            return "Error: category must contain at least one segment."

    from engrammar.db import get_connection, get_all_active_engrams
    from engrammar.embeddings import build_index
    from datetime import datetime

    conn = get_connection()
    row = conn.execute("SELECT * FROM engrams WHERE id = ?", (engram_id,)).fetchone()
    if not row:
        conn.close()
        return f"Error: engram #{engram_id} not found."

    now = datetime.utcnow().isoformat()
    updates = []
    params = []

    if text is not None:
        text = text.strip()
        updates.append("text = ?")
        params.append(text)

    if category is not None:
        # Sync junction table: remove old primary category, add new one
        old_category = row["category"]
        from engrammar.db import remove_engram_category, add_engram_category
        if old_category:
            remove_engram_category(engram_id, old_category)
        add_engram_category(engram_id, category)

        # Update primary category fields
        parts = category.strip("/").split("/")
        updates.append("category = ?")
        params.append(category)
        updates.append("level1 = ?")
        params.append(parts[0] if len(parts) > 0 else None)
        updates.append("level2 = ?")
        params.append(parts[1] if len(parts) > 1 else None)
        updates.append("level3 = ?")
        params.append(parts[2] if len(parts) > 2 else None)

    if prerequisites is not None:
        # Normalize to JSON string
        prereqs_json = None
        if isinstance(prerequisites, dict):
            prereqs_json = json.dumps(prerequisites)
        elif isinstance(prerequisites, str):
            try:
                json.loads(prerequisites)  # validate
                prereqs_json = prerequisites
            except json.JSONDecodeError:
                conn.close()
                return f"Error: prerequisites must be valid JSON."
        else:
            conn.close()
            return f"Error: prerequisites must be dict or JSON string."

        updates.append("prerequisites = ?")
        params.append(prereqs_json)

    if not updates:
        conn.close()
        return "Nothing to update — provide at least one of: text, category, prerequisites."

    updates.append("updated_at = ?")
    params.append(now)
    params.append(engram_id)

    conn.execute(f"UPDATE engrams SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()

    # Rebuild index if text changed
    if text is not None:
        engrams = get_all_active_engrams()
        build_index(engrams)

    return f"Updated engram #{engram_id}."


@mcp.tool()
def engrammar_categorize(engram_id: int, add: str | None = None, remove: str | None = None) -> str:
    """Manage multiple categories for a engram.

    Engrams can belong to multiple categories. The primary category (set via add/update)
    is used for display; additional categories improve search filtering.

    Args:
        engram_id: The engram ID
        add: Category path to add (e.g. "development/frontend/styling")
        remove: Category path to remove
    """
    from engrammar.db import get_engram_categories, add_engram_category, remove_engram_category, get_connection

    conn = get_connection()
    row = conn.execute("SELECT id FROM engrams WHERE id = ?", (engram_id,)).fetchone()
    conn.close()
    if not row:
        return f"Error: engram #{engram_id} not found."

    if not add and not remove:
        cats = get_engram_categories(engram_id)
        if cats:
            return f"Engram #{engram_id} categories: {', '.join(cats)}"
        return f"Engram #{engram_id} has no additional categories."

    parts = []
    if add:
        add_engram_category(engram_id, add)
        parts.append(f"Added category '{add}'")
    if remove:
        remove_engram_category(engram_id, remove)
        parts.append(f"Removed category '{remove}'")

    cats = get_engram_categories(engram_id)
    parts.append(f"Current categories: {', '.join(cats) if cats else 'none'}")

    return f"Engram #{engram_id}: " + ". ".join(parts)


@mcp.tool()
def engrammar_pin(engram_id: int, prerequisites: dict | str | None = None) -> str:
    """Pin a engram so it's always injected at session start when prerequisites match.

    Pinned engrams appear in every prompt's context for matching environments,
    regardless of search relevance. Use this for critical project rules.

    Args:
        engram_id: The engram ID to pin
        prerequisites: Optional prerequisites dict or JSON string for when to show this engram
            (e.g. {"paths":["~/work/acme"]} or {"repos":["app-repo"]})
    """
    from engrammar.db import get_connection
    from datetime import datetime

    conn = get_connection()
    row = conn.execute("SELECT text, category, pinned FROM engrams WHERE id = ?", (engram_id,)).fetchone()
    if not row:
        conn.close()
        return f"Error: engram #{engram_id} not found."

    if row["pinned"]:
        conn.close()
        return f"Engram #{engram_id} is already pinned."

    now = datetime.utcnow().isoformat()
    conn.execute("UPDATE engrams SET pinned = 1, updated_at = ? WHERE id = ?", (now, engram_id))

    if prerequisites:
        # Normalize to JSON string
        prereqs_json = None
        if isinstance(prerequisites, dict):
            prereqs_json = json.dumps(prerequisites)
        elif isinstance(prerequisites, str):
            try:
                json.loads(prerequisites)  # validate
                prereqs_json = prerequisites
            except json.JSONDecodeError:
                conn.close()
                return f"Error: prerequisites must be valid JSON."
        else:
            conn.close()
            return f"Error: prerequisites must be dict or JSON string."

        conn.execute("UPDATE engrams SET prerequisites = ?, updated_at = ? WHERE id = ?", (prereqs_json, now, engram_id))

    conn.commit()
    conn.close()
    return f"Pinned engram #{engram_id} [{row['category']}]: \"{row['text'][:80]}...\""


@mcp.tool()
def engrammar_unpin(engram_id: int) -> str:
    """Unpin a engram so it only appears via search relevance.

    Args:
        engram_id: The engram ID to unpin
    """
    from engrammar.db import get_connection
    from datetime import datetime

    conn = get_connection()
    row = conn.execute("SELECT text, category, pinned FROM engrams WHERE id = ?", (engram_id,)).fetchone()
    if not row:
        conn.close()
        return f"Error: engram #{engram_id} not found."

    if not row["pinned"]:
        conn.close()
        return f"Engram #{engram_id} is not pinned."

    now = datetime.utcnow().isoformat()
    conn.execute("UPDATE engrams SET pinned = 0, updated_at = ? WHERE id = ?", (now, engram_id))
    conn.commit()
    conn.close()
    return f"Unpinned engram #{engram_id} [{row['category']}]: \"{row['text'][:80]}...\""


@mcp.tool()
def engrammar_list(category: str | None = None, include_deprecated: bool = False, limit: int = 20, offset: int = 0) -> str:
    """List engrams in the knowledge base.

    Use this to see everything Engrammar knows, optionally filtered and paginated.

    Args:
        category: Optional category prefix filter (e.g. "development", "tools/figma")
        include_deprecated: Whether to include deprecated engrams (default False)
        limit: Max number of engrams to return (0 = all)
        offset: Number of engrams to skip (for pagination)
    """
    from engrammar.db import get_connection

    conn = get_connection()
    if include_deprecated:
        rows = conn.execute("SELECT * FROM engrams ORDER BY category, id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM engrams WHERE deprecated = 0 ORDER BY category, id").fetchall()
    conn.close()

    engrams = [dict(r) for r in rows]

    if category:
        engrams = [l for l in engrams if l.get("category", "").startswith(category)]

    total = len(engrams)

    if offset > 0:
        engrams = engrams[offset:]
    if limit > 0:
        engrams = engrams[:limit]

    if not engrams:
        return "No engrams found." + (f" (filter: {category})" if category else "")

    showing = f"Showing {len(engrams)} of {total}" if (limit > 0 or offset > 0) else f"Total: {total}"
    lines = [f"{showing} engrams\n"]
    current_cat = None
    for l in engrams:
        cat = l.get("category", "general")
        if cat != current_cat:
            current_cat = cat
            lines.append(f"\n## {cat}")

        flags = []
        if l.get("pinned"):
            flags.append("PINNED")
        if l.get("deprecated"):
            flags.append("DEPRECATED")
        status = (" [" + ", ".join(flags) + "]") if flags else ""
        prereqs = ""
        if l.get("prerequisites"):
            prereqs = f" | prereqs: {l['prerequisites']}"
        # Show additional categories from junction table
        from engrammar.db import get_engram_categories
        extra_cats = get_engram_categories(l["id"])
        extra_cats = [c for c in extra_cats if c != l.get("category")]
        cats_str = f" | also in: {', '.join(extra_cats)}" if extra_cats else ""
        lines.append(
            f"  #{l['id']}: {l['text']}"
            f"\n      matched: {l.get('times_matched', 0)}x | occurrences: {l.get('occurrence_count', 1)}"
            f"{prereqs}{cats_str}{status}"
        )

    return "\n".join(lines)


@mcp.tool()
def engrammar_status() -> str:
    """Show Engrammar system status — engram count, categories, index health."""
    from engrammar.db import get_engram_count, get_category_stats
    from engrammar.config import DB_PATH, INDEX_PATH

    lines = ["=== Engrammar Status ===\n"]

    if os.path.exists(DB_PATH):
        count = get_engram_count()
        lines.append(f"Engrams: {count} active")
        stats = get_category_stats()
        if stats:
            lines.append("\nCategories:")
            for cat, cnt in stats:
                lines.append(f"  {cat or 'uncategorized'}: {cnt}")
    else:
        lines.append("Database: NOT FOUND")

    if os.path.exists(INDEX_PATH):
        import numpy as np
        emb = np.load(INDEX_PATH, mmap_mode="r")
        lines.append(f"\nIndex: {emb.shape[0]} vectors x {emb.shape[1]} dims")
    else:
        lines.append("\nIndex: NOT BUILT")

    # Show environment
    from engrammar.environment import detect_environment
    env = detect_environment()
    lines.append(f"\nEnvironment:")
    lines.append(f"  OS: {env['os']}")
    lines.append(f"  Repo: {env.get('repo', 'unknown')}")
    lines.append(f"  MCP servers: {', '.join(env.get('mcp_servers', [])) or 'none detected'}")
    tags = env.get('tags', [])
    if tags:
        lines.append(f"  Tags: {', '.join(tags)}")
    else:
        lines.append(f"  Tags: none detected")

    return "\n".join(lines)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
