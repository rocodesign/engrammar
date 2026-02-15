"""Hybrid search: vector similarity + BM25 keyword search with Reciprocal Rank Fusion."""

import json
import os
import re

from rank_bm25 import BM25Okapi

from .config import LAST_SEARCH_PATH, load_config
from .db import get_all_active_lessons
from .embeddings import embed_text, load_index, vector_search
from .environment import check_prerequisites, detect_environment


def _tokenize(text):
    """Simple tokenizer for BM25."""
    return re.findall(r"\w+", text.lower())


def _reciprocal_rank_fusion(ranked_lists, k=60):
    """Merge multiple ranked lists using RRF.

    Args:
        ranked_lists: list of lists of (id, score) tuples
        k: RRF constant (default 60)

    Returns:
        list of (id, fused_score) tuples sorted by score descending
    """
    scores = {}
    for ranked_list in ranked_lists:
        for rank, (item_id, _) in enumerate(ranked_list):
            if item_id not in scores:
                scores[item_id] = 0.0
            scores[item_id] += 1.0 / (k + rank + 1)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def search(query, category_filter=None, tag_filter=None, top_k=None, db_path=None, skip_prerequisites=False):
    """Main hybrid search entry point.

    Args:
        query: search query string
        category_filter: optional category prefix to filter results (e.g. "development/frontend")
        tag_filter: optional list of required tags (lessons must have ALL specified tags)
        top_k: number of results (defaults to config value)
        db_path: optional database path override
        skip_prerequisites: if True, skip environment prerequisite filtering (used by backfill)

    Returns:
        list of dicts with lesson data + score
    """
    config = load_config()
    if top_k is None:
        top_k = config["search"]["top_k"]

    all_lessons = get_all_active_lessons(db_path=db_path)
    if not all_lessons:
        return []

    # Filter by environment prerequisites (unless skipped for backfill)
    if skip_prerequisites:
        lessons = all_lessons
        env = {}
    else:
        env = detect_environment()
        lessons = [l for l in all_lessons if check_prerequisites(l.get("prerequisites"), env)]
    if not lessons:
        return []

    # Build lesson lookup
    lesson_map = {l["id"]: l for l in lessons}

    # 1. Vector search
    vector_results = []
    try:
        query_embedding = embed_text(query)
        embeddings, ids = load_index()
        if embeddings is not None:
            vector_results = vector_search(query_embedding, embeddings, ids, top_k=10)
    except Exception:
        pass  # Fall back to BM25 only

    # 2. BM25 keyword search
    corpus = [_tokenize(l["text"] + " " + l.get("category", "")) for l in lessons]
    bm25 = BM25Okapi(corpus)
    query_tokens = _tokenize(query)
    bm25_scores = bm25.get_scores(query_tokens)

    bm25_ranked = sorted(
        [(lessons[i]["id"], float(bm25_scores[i])) for i in range(len(lessons))],
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    # 3. Reciprocal Rank Fusion
    fused = _reciprocal_rank_fusion([vector_results, bm25_ranked])

    # 3.5. Apply tag relevance boost (after RRF, before filters)
    env_tags = env.get("tags", [])
    if env_tags:
        from .db import get_avg_tag_relevance
        RELEVANCE_WEIGHT = 0.005  # small relative to RRF range ~0.014-0.033
        fused = [
            (lid, score + (get_avg_tag_relevance(lid, env_tags, db_path=db_path) / 3.0 * RELEVANCE_WEIGHT))
            for lid, score in fused
        ]
        fused.sort(key=lambda x: x[1], reverse=True)

    # 4. Apply category filter (check primary + junction table categories)
    if category_filter:
        from .db import get_connection
        conn = get_connection(db_path)
        rows = conn.execute(
            "SELECT lesson_id, category_path FROM lesson_categories WHERE category_path LIKE ?",
            (category_filter + "%",),
        ).fetchall()
        conn.close()
        junction_ids = {r["lesson_id"] for r in rows}

        fused = [
            (lid, score)
            for lid, score in fused
            if lid in lesson_map
            and (
                lesson_map[lid].get("category", "").startswith(category_filter)
                or lid in junction_ids
            )
        ]

    # 4.5. Apply tag filter (NEW)
    if tag_filter:
        required_tags = set(tag_filter if isinstance(tag_filter, list) else [tag_filter])
        fused = [
            (lid, score) for lid, score in fused
            if lid in lesson_map and _lesson_has_all_tags(lesson_map[lid], required_tags)
        ]

    # 5. Take top_k results (no threshold for RRF - it's rank-based, not similarity-based)
    results = []
    for lesson_id, score in fused[:top_k]:
        if lesson_id in lesson_map:
            result = dict(lesson_map[lesson_id])
            result["score"] = round(score, 4)
            results.append(result)

    # Save last search for introspection
    _save_last_search(query, results)

    return results


def _lesson_has_all_tags(lesson, required_tags):
    """Check if lesson has all required tags in prerequisites.

    Args:
        lesson: lesson dict with prerequisites field
        required_tags: set of tags that must all be present

    Returns:
        True if lesson has all required tags, False otherwise
    """
    prereqs = lesson.get("prerequisites")
    if not prereqs:
        return False

    prereq_dict = json.loads(prereqs) if isinstance(prereqs, str) else prereqs
    lesson_tags = set(prereq_dict.get("tags", []))
    return required_tags.issubset(lesson_tags)


def search_for_tool_context(tool_name, tool_input, db_path=None):
    """Specialized search for PreToolUse hook.

    Extracts keywords from tool_name + tool_input and runs hybrid search.

    Args:
        tool_name: name of the tool being used
        tool_input: dict of tool parameters

    Returns:
        list of matching lessons (top 2)
    """
    config = load_config()
    max_results = config["display"]["max_lessons_per_tool"]

    # Extract relevant keywords
    keywords = [tool_name]

    if isinstance(tool_input, dict):
        # Extract file paths
        for key in ("file_path", "path", "pattern", "command"):
            val = tool_input.get(key, "")
            if val:
                keywords.append(str(val))

        # Extract from command for Bash
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            # Extract first word (the actual command)
            parts = cmd.split()
            if parts:
                keywords.append(parts[0])

    query = " ".join(keywords)
    return search(query, top_k=max_results, db_path=db_path)


def _save_last_search(query, results):
    """Save last search results for introspection."""
    try:
        data = {
            "query": query,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            "result_count": len(results),
            "results": [
                {
                    "id": r["id"],
                    "text": r["text"][:100],
                    "category": r.get("category", ""),
                    "score": r.get("score", 0),
                }
                for r in results
            ],
        }
        with open(LAST_SEARCH_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass  # Non-critical
