"""Engrammar MCP server — gives Claude direct access to lesson management."""

import json
import os
import sys

# Ensure engrammar package is importable
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "engrammar",
    instructions=(
        "Engrammar is your semantic knowledge system. Use it to search past lessons, "
        "add new learnings, mark lessons as not applicable, and check system status. "
        "Lessons from hooks appear in [ENGRAMMAR_V1] blocks with EG#ID markers "
        "(e.g. [EG#42]). When you notice a lesson from hook context doesn't apply "
        "to the current environment, use engrammar_feedback to record why."
    ),
)


@mcp.tool()
def engrammar_search(query: str, category: str | None = None, tags: list[str] | None = None, top_k: int = 5) -> str:
    """Search lessons by semantic similarity + keyword matching.

    Use this to find relevant lessons for the current task.

    Args:
        query: Natural language search query
        category: Optional category prefix filter (e.g. "development/frontend")
        tags: Optional list of required tags (lessons must have ALL specified tags)
        top_k: Number of results to return (default 5)
    """
    from engrammar.search import search

    results = search(query, category_filter=category, tag_filter=tags, top_k=top_k)

    if not results:
        return "No matching lessons found."

    lines = [f"Found {len(results)} lessons:\n"]
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
    """Add a new lesson to the knowledge base.

    Use this when you learn something that should be remembered across sessions.

    Args:
        text: The lesson text — what was learned
        category: Hierarchical category (e.g. "development/frontend/styling")
        tags: Optional list of environment tags (e.g. ["acme", "react", "frontend"])
        prerequisites: Optional requirements dict or JSON string (e.g. {"repos":["app-repo"],"os":["darwin"]})
        source: How this lesson was discovered ("manual", "auto-extracted", "feedback")
    """
    from engrammar.db import add_lesson, get_all_active_lessons
    from engrammar.embeddings import build_index

    # Normalize prerequisites to JSON string
    prereqs_json = None
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

    if prereqs_dict:
        prereqs_json = json.dumps(prereqs_dict)

    lesson_id = add_lesson(text=text, category=category, source=source)

    # Update prerequisites if provided
    if prereqs_json:
        from engrammar.db import get_connection
        conn = get_connection()
        conn.execute("UPDATE lessons SET prerequisites = ? WHERE id = ?", (prereqs_json, lesson_id))
        conn.commit()
        conn.close()

    # Rebuild index
    lessons = get_all_active_lessons()
    build_index(lessons)

    return f"Added lesson #{lesson_id} in category '{category}'. Index rebuilt with {len(lessons)} lessons."


@mcp.tool()
def engrammar_deprecate(lesson_id: int, reason: str = "") -> str:
    """Deprecate a lesson that is no longer accurate or useful.

    Use this when a lesson is outdated, wrong, or superseded.

    Args:
        lesson_id: The lesson ID to deprecate
        reason: Why this lesson is being deprecated
    """
    from engrammar.db import deprecate_lesson, get_connection, get_all_active_lessons
    from engrammar.embeddings import build_index

    # Verify lesson exists
    conn = get_connection()
    row = conn.execute("SELECT text, category FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    conn.close()

    if not row:
        return f"Error: lesson #{lesson_id} not found."

    deprecate_lesson(lesson_id)

    # Rebuild index without deprecated lesson
    lessons = get_all_active_lessons()
    build_index(lessons)

    return f"Deprecated lesson #{lesson_id} [{row['category']}]: \"{row['text'][:80]}...\"\nReason: {reason}\nIndex rebuilt with {len(lessons)} active lessons."


@mcp.tool()
def engrammar_feedback(
    lesson_id: int,
    applicable: bool,
    reason: str = "",
    add_prerequisites: dict | str | None = None,
) -> str:
    """Give feedback on a lesson that was surfaced by hooks.

    Use this when a lesson from hook context doesn't apply to the current
    environment or situation. This helps Engrammar learn when to surface lessons.

    Args:
        lesson_id: The lesson ID (shown in search results as id:N)
        applicable: Whether the lesson was applicable in this context
        reason: Why the lesson did/didn't apply (e.g. "requires figma MCP which isn't connected")
        add_prerequisites: Optional prerequisites dict or JSON string to add
            (e.g. {"mcp_servers":["figma"],"repos":["app-repo"]})
    """
    from engrammar.db import get_connection
    from datetime import datetime

    conn = get_connection()
    row = conn.execute("SELECT text, category, prerequisites FROM lessons WHERE id = ?", (lesson_id,)).fetchone()

    if not row:
        conn.close()
        return f"Error: lesson #{lesson_id} not found."

    now = datetime.utcnow().isoformat()
    response_parts = []

    if applicable:
        # Positive feedback — increment match count
        conn.execute(
            "UPDATE lessons SET times_matched = times_matched + 1, last_matched = ? WHERE id = ?",
            (now, lesson_id),
        )
        response_parts.append(f"Recorded positive feedback for lesson #{lesson_id}.")
    else:
        # Negative feedback — record reason
        response_parts.append(f"Recorded negative feedback for lesson #{lesson_id}: {reason}")

    # Add prerequisites if provided
    if add_prerequisites:
        # Normalize to dict
        if isinstance(add_prerequisites, str):
            try:
                new_prereqs = json.loads(add_prerequisites)
            except json.JSONDecodeError:
                response_parts.append(f"Warning: invalid prerequisites JSON, skipped: {add_prerequisites}")
                conn.commit()
                conn.close()
                return "\n".join(response_parts)
        elif isinstance(add_prerequisites, dict):
            new_prereqs = add_prerequisites
        else:
            response_parts.append(f"Warning: prerequisites must be dict or JSON string, skipped")
            conn.commit()
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
            "UPDATE lessons SET prerequisites = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing), now, lesson_id),
        )
        response_parts.append(f"Updated prerequisites: {json.dumps(existing)}")

    conn.commit()
    conn.close()

    return "\n".join(response_parts)


@mcp.tool()
def engrammar_update(
    lesson_id: int,
    text: str | None = None,
    category: str | None = None,
    prerequisites: dict | str | None = None,
) -> str:
    """Update an existing lesson's text, category, or prerequisites.

    Args:
        lesson_id: The lesson ID to update
        text: New lesson text (if changing)
        category: New category (if changing)
        prerequisites: New prerequisites dict or JSON string (if changing)
    """
    from engrammar.db import get_connection, get_all_active_lessons
    from engrammar.embeddings import build_index
    from datetime import datetime

    conn = get_connection()
    row = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    if not row:
        conn.close()
        return f"Error: lesson #{lesson_id} not found."

    now = datetime.utcnow().isoformat()
    updates = []
    params = []

    if text is not None:
        updates.append("text = ?")
        params.append(text)

    if category is not None:
        # Sync junction table: remove old primary category, add new one
        old_category = row["category"]
        from engrammar.db import remove_lesson_category, add_lesson_category
        if old_category:
            remove_lesson_category(lesson_id, old_category)
        add_lesson_category(lesson_id, category)

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
    params.append(lesson_id)

    conn.execute(f"UPDATE lessons SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()

    # Rebuild index if text changed
    if text is not None:
        lessons = get_all_active_lessons()
        build_index(lessons)

    return f"Updated lesson #{lesson_id}."


@mcp.tool()
def engrammar_categorize(lesson_id: int, add: str | None = None, remove: str | None = None) -> str:
    """Manage multiple categories for a lesson.

    Lessons can belong to multiple categories. The primary category (set via add/update)
    is used for display; additional categories improve search filtering.

    Args:
        lesson_id: The lesson ID
        add: Category path to add (e.g. "development/frontend/styling")
        remove: Category path to remove
    """
    from engrammar.db import get_lesson_categories, add_lesson_category, remove_lesson_category, get_connection

    conn = get_connection()
    row = conn.execute("SELECT id FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    conn.close()
    if not row:
        return f"Error: lesson #{lesson_id} not found."

    if not add and not remove:
        cats = get_lesson_categories(lesson_id)
        if cats:
            return f"Lesson #{lesson_id} categories: {', '.join(cats)}"
        return f"Lesson #{lesson_id} has no additional categories."

    parts = []
    if add:
        add_lesson_category(lesson_id, add)
        parts.append(f"Added category '{add}'")
    if remove:
        remove_lesson_category(lesson_id, remove)
        parts.append(f"Removed category '{remove}'")

    cats = get_lesson_categories(lesson_id)
    parts.append(f"Current categories: {', '.join(cats) if cats else 'none'}")

    return f"Lesson #{lesson_id}: " + ". ".join(parts)


@mcp.tool()
def engrammar_pin(lesson_id: int, prerequisites: dict | str | None = None) -> str:
    """Pin a lesson so it's always injected at session start when prerequisites match.

    Pinned lessons appear in every prompt's context for matching environments,
    regardless of search relevance. Use this for critical project rules.

    Args:
        lesson_id: The lesson ID to pin
        prerequisites: Optional prerequisites dict or JSON string for when to show this lesson
            (e.g. {"paths":["~/work/acme"]} or {"repos":["app-repo"]})
    """
    from engrammar.db import get_connection
    from datetime import datetime

    conn = get_connection()
    row = conn.execute("SELECT text, category, pinned FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    if not row:
        conn.close()
        return f"Error: lesson #{lesson_id} not found."

    if row["pinned"]:
        conn.close()
        return f"Lesson #{lesson_id} is already pinned."

    now = datetime.utcnow().isoformat()
    conn.execute("UPDATE lessons SET pinned = 1, updated_at = ? WHERE id = ?", (now, lesson_id))

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

        conn.execute("UPDATE lessons SET prerequisites = ?, updated_at = ? WHERE id = ?", (prereqs_json, now, lesson_id))

    conn.commit()
    conn.close()
    return f"Pinned lesson #{lesson_id} [{row['category']}]: \"{row['text'][:80]}...\""


@mcp.tool()
def engrammar_unpin(lesson_id: int) -> str:
    """Unpin a lesson so it only appears via search relevance.

    Args:
        lesson_id: The lesson ID to unpin
    """
    from engrammar.db import get_connection
    from datetime import datetime

    conn = get_connection()
    row = conn.execute("SELECT text, category, pinned FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    if not row:
        conn.close()
        return f"Error: lesson #{lesson_id} not found."

    if not row["pinned"]:
        conn.close()
        return f"Lesson #{lesson_id} is not pinned."

    now = datetime.utcnow().isoformat()
    conn.execute("UPDATE lessons SET pinned = 0, updated_at = ? WHERE id = ?", (now, lesson_id))
    conn.commit()
    conn.close()
    return f"Unpinned lesson #{lesson_id} [{row['category']}]: \"{row['text'][:80]}...\""


@mcp.tool()
def engrammar_list(category: str | None = None, include_deprecated: bool = False, limit: int = 20, offset: int = 0) -> str:
    """List lessons in the knowledge base.

    Use this to see everything Engrammar knows, optionally filtered and paginated.

    Args:
        category: Optional category prefix filter (e.g. "development", "tools/figma")
        include_deprecated: Whether to include deprecated lessons (default False)
        limit: Max number of lessons to return (0 = all)
        offset: Number of lessons to skip (for pagination)
    """
    from engrammar.db import get_connection

    conn = get_connection()
    if include_deprecated:
        rows = conn.execute("SELECT * FROM lessons ORDER BY category, id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM lessons WHERE deprecated = 0 ORDER BY category, id").fetchall()
    conn.close()

    lessons = [dict(r) for r in rows]

    if category:
        lessons = [l for l in lessons if l.get("category", "").startswith(category)]

    total = len(lessons)

    if offset > 0:
        lessons = lessons[offset:]
    if limit > 0:
        lessons = lessons[:limit]

    if not lessons:
        return "No lessons found." + (f" (filter: {category})" if category else "")

    showing = f"Showing {len(lessons)} of {total}" if (limit > 0 or offset > 0) else f"Total: {total}"
    lines = [f"{showing} lessons\n"]
    current_cat = None
    for l in lessons:
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
        from engrammar.db import get_lesson_categories
        extra_cats = get_lesson_categories(l["id"])
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
    """Show Engrammar system status — lesson count, categories, index health."""
    from engrammar.db import get_lesson_count, get_category_stats
    from engrammar.config import DB_PATH, INDEX_PATH

    lines = ["=== Engrammar Status ===\n"]

    if os.path.exists(DB_PATH):
        count = get_lesson_count()
        lines.append(f"Lessons: {count} active")
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
