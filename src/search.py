"""Hybrid search: vector similarity + BM25 keyword search with Reciprocal Rank Fusion."""

import json
import os
import re

from rank_bm25 import BM25Okapi

from .config import LAST_SEARCH_PATH, load_config
from .db import get_all_active_engrams
from .embeddings import embed_text, load_index, load_tag_index, vector_search
from .environment import detect_environment


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
        tag_filter: optional list of required tags (engrams must have ALL specified tags)
        top_k: number of results (defaults to config value)
        db_path: optional database path override
        skip_prerequisites: if True, skip environment prerequisite filtering (used by backfill)

    Returns:
        list of dicts with engram data + score
    """
    config = load_config()
    if top_k is None:
        top_k = config["search"]["top_k"]

    all_engrams = get_all_active_engrams(db_path=db_path)
    if not all_engrams:
        return []

    # Detect environment (skip_prerequisites sets env={} which naturally skips tag filtering)
    if skip_prerequisites:
        env = {}
    else:
        env = detect_environment()

    engrams = all_engrams

    # Build engram lookup
    engram_map = {l["id"]: l for l in engrams}

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
    corpus = [_tokenize(l["text"] + " " + l.get("category", "")) for l in engrams]
    bm25 = BM25Okapi(corpus)
    query_tokens = _tokenize(query)
    bm25_scores = bm25.get_scores(query_tokens)

    bm25_ranked = sorted(
        [(engrams[i]["id"], float(bm25_scores[i])) for i in range(len(engrams))],
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    # 3. Reciprocal Rank Fusion
    # Scale k with engram count so rank position carries real weight.
    # k=60 (the default from web search) compresses 50 engrams into a
    # ~15% spread; k=N/5 gives ~2x spread between rank 0 and rank 9.
    rrf_k = max(1, len(engrams) // 5)
    fused = _reciprocal_rank_fusion([vector_results, bm25_ranked], k=rrf_k)

    # 3.1. Environment tag affinity boost
    # Use precomputed tag embeddings for a vectorized cosine similarity
    # instead of per-engram embed calls. Falls back to per-engram embedding
    # if the tag index is unavailable.
    # Engrams without prerequisite tags are treated as generic (neutral).
    env_tags = env.get("tags", [])
    if env_tags:
        try:
            import numpy as np
            env_tag_emb = embed_text(" ".join(env_tags))

            # Try precomputed tag index first
            tag_embeddings, tag_ids = load_tag_index()
            if tag_embeddings is not None:
                # Vectorized: compute all tag similarities at once
                env_norm = env_tag_emb / (np.linalg.norm(env_tag_emb) + 1e-10)
                tag_norms = np.linalg.norm(tag_embeddings, axis=1, keepdims=True) + 1e-10
                tag_emb_norm = tag_embeddings / tag_norms
                all_sims = tag_emb_norm @ env_norm
                tag_sim_map = {int(tag_ids[i]): float(all_sims[i]) for i in range(len(tag_ids))}

                boosted = []
                for lid, score in fused:
                    sim = tag_sim_map.get(lid)
                    if sim is None:
                        boosted.append((lid, score))
                        continue
                    # Map similarity to multiplier:
                    # sim ~0.65 (unrelated stack) → ~0.5x penalty
                    # sim ~0.80 (partial match)   → ~0.9x neutral
                    # sim ~0.95+ (same stack)     → ~1.3x boost
                    multiplier = max(0.5, min(1.3, (sim - 0.65) / 0.30 * 0.8 + 0.5))
                    boosted.append((lid, score * multiplier))
            else:
                # Fallback: per-engram embedding (no tag index built yet)
                boosted = []
                for lid, score in fused:
                    engram = engram_map.get(lid)
                    if not engram:
                        boosted.append((lid, score))
                        continue
                    prereqs = engram.get("prerequisites")
                    if not prereqs:
                        boosted.append((lid, score))
                        continue
                    prereq_dict = json.loads(prereqs) if isinstance(prereqs, str) else prereqs
                    engram_tags = prereq_dict.get("tags", [])
                    if not engram_tags:
                        boosted.append((lid, score))
                        continue
                    engram_tag_emb = embed_text(" ".join(engram_tags))
                    sim = float(np.dot(env_tag_emb, engram_tag_emb) / (
                        np.linalg.norm(env_tag_emb) * np.linalg.norm(engram_tag_emb)
                    ))
                    multiplier = max(0.5, min(1.3, (sim - 0.65) / 0.30 * 0.8 + 0.5))
                    boosted.append((lid, score * multiplier))

            fused = sorted(boosted, key=lambda x: x[1], reverse=True)
        except Exception:
            pass

    # 3.5. Tag relevance filter + boost (after RRF, before category/tag filters)
    env_tags = env.get("tags", [])
    if env_tags:
        from .db import get_tag_relevance_with_evidence
        MIN_EVALS_FOR_FILTER = 3        # minimum evidence before filtering
        NEGATIVE_SCORE_THRESHOLD = -0.1  # filter out if avg below this with enough evidence
        RELEVANCE_WEIGHT = 0.01          # boost weight (RRF range ~0.014-0.033)

        filtered_fused = []
        for lid, score in fused:
            avg_score, total_evals = get_tag_relevance_with_evidence(lid, env_tags, db_path=db_path)
            # Filter: strong negative signal with enough evidence
            if total_evals >= MIN_EVALS_FOR_FILTER and avg_score < NEGATIVE_SCORE_THRESHOLD:
                continue
            # Boost: apply tag relevance as score adjustment
            score += (avg_score / 3.0) * RELEVANCE_WEIGHT
            filtered_fused.append((lid, score))

        fused = sorted(filtered_fused, key=lambda x: x[1], reverse=True)

    # 4. Apply category filter (check primary + junction table categories)
    if category_filter:
        from .db import get_connection
        conn = get_connection(db_path)
        rows = conn.execute(
            "SELECT engram_id, category_path FROM engram_categories WHERE category_path LIKE ?",
            (category_filter + "%",),
        ).fetchall()
        conn.close()
        junction_ids = {r["engram_id"] for r in rows}

        fused = [
            (lid, score)
            for lid, score in fused
            if lid in engram_map
            and (
                engram_map[lid].get("category", "").startswith(category_filter)
                or lid in junction_ids
            )
        ]

    # 4.5. Apply tag filter (NEW)
    if tag_filter:
        required_tags = set(tag_filter if isinstance(tag_filter, list) else [tag_filter])
        fused = [
            (lid, score) for lid, score in fused
            if lid in engram_map and _engram_has_all_tags(engram_map[lid], required_tags)
        ]

    # 5. Take top_k results (no threshold for RRF - it's rank-based, not similarity-based)
    results = []
    for engram_id, score in fused[:top_k]:
        if engram_id in engram_map:
            result = dict(engram_map[engram_id])
            result["score"] = round(score, 4)
            results.append(result)

    # Save last search for introspection
    _save_last_search(query, results)

    return results


def _engram_has_all_tags(engram, required_tags):
    """Check if engram has all required tags in prerequisites.

    Args:
        engram: engram dict with prerequisites field
        required_tags: set of tags that must all be present

    Returns:
        True if engram has all required tags, False otherwise
    """
    prereqs = engram.get("prerequisites")
    if not prereqs:
        return False

    prereq_dict = json.loads(prereqs) if isinstance(prereqs, str) else prereqs
    engram_tags = set(prereq_dict.get("tags", []))
    return required_tags.issubset(engram_tags)


def _build_tool_query(tool_name, tool_input):
    """Build a semantic search query from tool name and input.

    Routes by tool type to extract the most meaningful keywords
    rather than dumping raw parameters into the query.
    """
    if not isinstance(tool_input, dict):
        return tool_name

    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        parts = cmd.split()
        if not parts:
            return None  # skip empty commands

        base_cmd = parts[0]

        # Git commands — use subcommand for semantic search
        if base_cmd == "git":
            subcmd = parts[1] if len(parts) > 1 else ""
            git_queries = {
                "commit": "git commit conventions",
                "push": "git push deploy",
                "checkout": "git branch naming",
                "branch": "git branch naming",
                "rebase": "git rebase workflow",
                "merge": "git merge workflow",
            }
            return git_queries.get(subcmd, f"git {subcmd}")

        # GitHub CLI
        if base_cmd == "gh":
            subcmd = " ".join(parts[1:3]) if len(parts) > 2 else parts[1] if len(parts) > 1 else ""
            gh_queries = {
                "pr create": "pull request create description template",
                "pr view": "pull request review",
                "pr review": "pull request review feedback",
                "pr merge": "pull request merge",
                "issue create": "issue create",
            }
            return gh_queries.get(subcmd, f"github {subcmd}")

        # Test runners
        if base_cmd in ("jest", "pytest", "cypress", "vitest", "npx"):
            test_hint = " ".join(parts[:3])
            return f"testing {test_hint}"

        # npm/yarn/pnpm scripts
        if base_cmd in ("npm", "yarn", "pnpm"):
            script = parts[1] if len(parts) > 1 else ""
            if script in ("test", "t"):
                return "testing npm test"
            if script in ("run",) and len(parts) > 2:
                return f"{parts[2]} script"
            return f"{base_cmd} {script}"

        # Package install
        if base_cmd in ("pip", "uv"):
            return f"python package {' '.join(parts[1:3])}"

        # Generic — use first 3 words
        return " ".join(parts[:3])

    if tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return None

        # Extract file extension and meaningful path segments
        import os
        basename = os.path.basename(file_path)
        ext = os.path.splitext(basename)[1]

        ext_context = {
            ".tsx": "react typescript component",
            ".ts": "typescript",
            ".jsx": "react component",
            ".js": "javascript",
            ".py": "python",
            ".css": "styling css",
            ".scss": "styling scss",
            ".md": "documentation markdown",
        }

        # Cypress/Storybook file patterns
        if ".cy." in basename:
            context = "cypress testing"
        elif ".stories." in basename:
            context = "storybook stories"
        elif ".test." in basename or ".spec." in basename:
            context = "unit testing"
        else:
            context = ext_context.get(ext, "")

        # Use last 2-3 path segments for project context
        path_parts = file_path.split("/")
        path_context = "/".join(path_parts[-3:]) if len(path_parts) > 3 else file_path

        return f"editing {context} {path_context}".strip()

    if tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return None
        import os
        basename = os.path.basename(file_path)
        path_parts = file_path.split("/")
        path_context = "/".join(path_parts[-3:]) if len(path_parts) > 3 else file_path
        return f"writing {basename} {path_context}"

    if tool_name == "Skill":
        skill = tool_input.get("skill", "")
        return f"{skill} skill" if skill else None

    if tool_name == "Task":
        # Task tool has a description field
        desc = tool_input.get("description", "")
        return desc if desc else None

    # For other tools, use whatever params are available
    keywords = [tool_name]
    for key in ("file_path", "path", "pattern", "query"):
        val = tool_input.get(key, "")
        if val:
            keywords.append(str(val)[:100])
    return " ".join(keywords) if len(keywords) > 1 else None


def search_for_tool_context(tool_name, tool_input, db_path=None):
    """Specialized search for PreToolUse hook.

    Builds a semantic query from tool name + input and runs hybrid search.
    Returns empty list if the tool context is too shallow for useful search.

    Args:
        tool_name: name of the tool being used
        tool_input: dict of tool parameters

    Returns:
        list of matching engrams (top 2)
    """
    config = load_config()
    max_results = config["display"]["max_engrams_per_tool"]

    query = _build_tool_query(tool_name, tool_input)
    if not query:
        return []
    results = search(query, top_k=max_results, db_path=db_path)

    # Apply minimum score threshold — tool context is shallow,
    # so filter out low-confidence matches that would just be noise.
    min_score = config["hooks"].get("min_score_tool", 0.025)
    if min_score:
        results = [r for r in results if r.get("score", 0) >= min_score]

    return results


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
