"""Hybrid search: vector similarity + BM25 keyword search with Reciprocal Rank Fusion."""

import json
import os
import re

from rank_bm25 import BM25Okapi

from engrammar.core.config import LAST_SEARCH_PATH, load_config
from engrammar.core.db import get_all_active_engrams
from engrammar.core.embeddings import embed_text, load_index, load_tag_index, vector_search
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


def search(
    query,
    category_filter=None,
    tag_filter=None,
    top_k=None,
    db_path=None,
    skip_prerequisites=False,
    enforce_prerequisites=False,
    cwd=None,
    return_diagnostics=False,
):
    """Main hybrid search entry point.

    Args:
        query: search query string
        category_filter: optional category prefix to filter results (e.g. "development/frontend")
        tag_filter: optional list of required tags (engrams must have ALL specified tags)
        top_k: number of results (defaults to config value)
        db_path: optional database path override
        skip_prerequisites: if True, skip environment prerequisite filtering (used by backfill)
        enforce_prerequisites: if True, apply min_score_prompt threshold from config
            (used by prompt/tool hooks to filter low-confidence matches)

    Returns:
        list of dicts with engram data + score
    """
    config = load_config()
    if top_k is None:
        top_k = config["search"]["top_k"]

    # Component diagnostics tracker (per engram_id)
    diag = {} if return_diagnostics else None

    # Pre-filter: skip low-information queries before any embedding work
    from .query_filter import is_low_information
    should_skip, skip_reason = is_low_information(query)
    if should_skip:
        _save_last_search(query, [])
        if return_diagnostics:
            return [], {"abstained": True, "skip_reason": skip_reason}
        return []

    all_engrams = get_all_active_engrams(db_path=db_path)
    if not all_engrams:
        return ([], {}) if return_diagnostics else []

    # Detect environment (skip_prerequisites sets env={} which naturally skips tag filtering)
    if skip_prerequisites:
        env = {}
    else:
        env = detect_environment(cwd=cwd)

    engrams = all_engrams

    if not engrams:
        _save_last_search(query, [])
        return []

    # Build engram lookup
    engram_map = {l["id"]: l for l in engrams}

    # 1. Vector search
    vector_results = []
    try:
        query_embedding = embed_text(query)
        embeddings, ids = load_index()
        if embeddings is not None:
            vector_results = vector_search(query_embedding, embeddings, ids, top_k=10)
            allowed_ids = set(engram_map.keys())
            vector_results = [(lid, score) for lid, score in vector_results if lid in allowed_ids]
    except Exception:
        pass  # Fall back to BM25 only

    # 2. BM25 keyword search
    corpus = [_tokenize(l["text"] + " " + l.get("category", "")) for l in engrams]
    bm25 = BM25Okapi(corpus)
    query_tokens = _tokenize(query)
    bm25_scores = bm25.get_scores(query_tokens)

    query_token_set = set(query_tokens)
    bm25_ranked = sorted(
        [
            (engrams[i]["id"], float(bm25_scores[i]))
            for i in range(len(engrams))
            if query_token_set.intersection(corpus[i])
        ],
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    if not vector_results and not bm25_ranked:
        _save_last_search(query, [])
        return ([], {}) if return_diagnostics else []

    # 2.5. Abstain for low-information queries
    # If the best vector similarity is below threshold, the query is too vague
    # to produce meaningful results (e.g., "still running?", "Yeah, that's true")
    abstain_threshold = config.get("scoring", {}).get("abstain_threshold", 0.0)
    if abstain_threshold > 0 and vector_results:
        best_vector_sim = vector_results[0][1] if vector_results else 0
        if best_vector_sim < abstain_threshold:
            _save_last_search(query, [])
            return ([], {"abstained": True, "best_vector_sim": best_vector_sim}) if return_diagnostics else []

    # 3. Reciprocal Rank Fusion
    # Scale k with engram count so rank position carries real weight.
    # k=60 (the default from web search) compresses 50 engrams into a
    # ~15% spread; k=N/5 gives ~2x spread between rank 0 and rank 9.
    rrf_k = max(1, len(engrams) // 5)
    fused = _reciprocal_rank_fusion([vector_results, bm25_ranked], k=rrf_k)

    # 3.1. Normalize RRF scores to 0-1 using fixed anchors
    scoring_config = config.get("scoring", {})
    rrf_floor = scoring_config.get("rrf_floor", 0.015)
    rrf_ceiling = scoring_config.get("rrf_ceiling", 0.033)
    rrf_range = rrf_ceiling - rrf_floor
    if rrf_range > 0:
        fused = [(lid, (score - rrf_floor) / rrf_range) for lid, score in fused]

    # Record raw vector + BM25 + RRF diagnostics
    if diag is not None:
        vector_map = dict(vector_results)
        bm25_map = dict(bm25_ranked)
        for lid, score in fused:
            diag[lid] = {
                "vector_sim": round(vector_map.get(lid, 0.0), 4),
                "bm25": round(bm25_map.get(lid, 0.0), 4),
                "rrf_normalized": round(score, 4),
                "repo_delta": 0.0,
                "feedback_delta": 0.0,
                "tag_affinity": 0.0,
                "best_tag_sim": 0.0,
                "tag_bonus": 0.0,
            }

    # 3.2. Repo prior from engram_repo_stats (replaces repo:* tag matching)
    current_repo = env.get("repo")
    if current_repo:
        from engrammar.core.db import get_connection
        repo_match_boost = scoring_config.get("repo_match_boost", 0.05)
        repo_mismatch_penalty = scoring_config.get("repo_mismatch_penalty", -0.08)

        # Batch-load repo stats for all candidates
        candidate_ids = [lid for lid, _ in fused]
        repo_stats_map = {}  # engram_id -> {repo: times_matched}
        if candidate_ids:
            conn = get_connection(db_path)
            placeholders = ",".join("?" for _ in candidate_ids)
            rows = conn.execute(
                f"SELECT engram_id, repo, times_matched FROM engram_repo_stats WHERE engram_id IN ({placeholders})",
                candidate_ids,
            ).fetchall()
            conn.close()
            for r in rows:
                repo_stats_map.setdefault(r["engram_id"], {})[r["repo"]] = r["times_matched"]

        adjusted = []
        for lid, score in fused:
            stats = repo_stats_map.get(lid, {})
            repo_delta = 0.0
            if stats:
                if current_repo in stats:
                    repo_delta = repo_match_boost
                else:
                    repo_delta = repo_mismatch_penalty
                score += repo_delta
            if diag is not None and lid in diag:
                diag[lid]["repo_delta"] = round(repo_delta, 4)
            adjusted.append((lid, score))
        fused = adjusted

    # 3.5. Tag relevance filter + boost (keyed by engram's content tags)
    from engrammar.core.db import get_tag_relevance_with_evidence, get_content_tags_batch
    MIN_EVALS_FOR_FILTER = 3        # minimum evidence before filtering
    NEGATIVE_SCORE_THRESHOLD = -0.1  # filter out if avg below this with enough evidence
    RELEVANCE_WEIGHT = scoring_config.get("weight_feedback", 0.20)

    # Batch-load content tags for all candidates
    candidate_ids = [lid for lid, _ in fused]
    content_tags_map = get_content_tags_batch(candidate_ids, db_path=db_path) if candidate_ids else {}

    filtered_fused = []
    for lid, score in fused:
        engram_content_tags = content_tags_map.get(lid, [])
        if engram_content_tags:
            avg_score, total_evals = get_tag_relevance_with_evidence(lid, engram_content_tags, db_path=db_path)
            # Filter: strong negative signal with enough evidence
            if total_evals >= MIN_EVALS_FOR_FILTER and avg_score < NEGATIVE_SCORE_THRESHOLD:
                continue
            # Boost: apply tag relevance as score adjustment
            feedback_delta = (avg_score / 3.0) * RELEVANCE_WEIGHT
            score += feedback_delta
            if diag is not None and lid in diag:
                diag[lid]["feedback_delta"] = round(feedback_delta, 4)
        filtered_fused.append((lid, score))

    fused = sorted(filtered_fused, key=lambda x: x[1], reverse=True)

    # 3.6. Content tag affinity (per-tag matching with thresholded scoring)
    w_content = scoring_config.get("weight_content_tag", 0.10)
    tag_sim_floor = scoring_config.get("tag_sim_floor", 0.45)
    tag_sim_ceiling = scoring_config.get("tag_sim_ceiling", 0.75)
    tag_mismatch_penalty = scoring_config.get("tag_mismatch_penalty", -0.05)
    tag_mismatch_threshold = scoring_config.get("tag_mismatch_threshold", 0.20)
    prompt_tags = []
    if w_content > 0 and query:
        try:
            from engrammar.search.prompt_tags import detect_prompt_tags
            from engrammar.core.embeddings import embed_text as _embed_text
            import numpy as np

            prompt_tag_top_k = scoring_config.get("prompt_tag_top_k", 3)
            prompt_tag_threshold = scoring_config.get("prompt_tag_threshold", 0.45)
            prompt_tags = detect_prompt_tags(query, top_k=prompt_tag_top_k, threshold=prompt_tag_threshold)

            if prompt_tags:
                # Pre-embed each prompt tag individually
                prompt_tag_embs = []
                for tag, _score in prompt_tags:
                    emb = _embed_text(tag)
                    prompt_tag_embs.append(emb / (np.linalg.norm(emb) + 1e-10))

                # Pre-embed all unique engram content tags
                all_engram_tags = set()
                for lid, _ in fused:
                    for t in content_tags_map.get(lid, []):
                        all_engram_tags.add(t)

                engram_tag_emb_cache = {}
                for t in all_engram_tags:
                    emb = _embed_text(t)
                    engram_tag_emb_cache[t] = emb / (np.linalg.norm(emb) + 1e-10)

                # Per-engram: best prompt-tag to engram-tag match
                content_scored = []
                for lid, score in fused:
                    engram_tags = content_tags_map.get(lid, [])
                    if engram_tags and prompt_tag_embs:
                        # Find best similarity across all prompt-tag × engram-tag pairs
                        best_sim = -1.0
                        for pt_emb in prompt_tag_embs:
                            for et in engram_tags:
                                et_emb = engram_tag_emb_cache[et]
                                sim = float(np.dot(pt_emb, et_emb))
                                if sim > best_sim:
                                    best_sim = sim

                        # Thresholded ramp: zero below floor, linear to ceiling, capped at 1.0
                        tag_range = tag_sim_ceiling - tag_sim_floor
                        if best_sim < tag_sim_floor:
                            tag_bonus = 0.0
                        elif tag_range > 0 and best_sim < tag_sim_ceiling:
                            tag_bonus = (best_sim - tag_sim_floor) / tag_range
                        else:
                            tag_bonus = 1.0

                        score += w_content * tag_bonus

                        if diag is not None and lid in diag:
                            diag[lid]["best_tag_sim"] = round(best_sim, 4)
                            diag[lid]["tag_bonus"] = round(tag_bonus, 4)
                            diag[lid]["tag_affinity"] = round(w_content * tag_bonus, 4)

                        # Penalty for strong mismatch when prompt tags exist
                        if best_sim < tag_mismatch_threshold:
                            score += tag_mismatch_penalty
                            if diag is not None and lid in diag:
                                diag[lid]["tag_affinity"] = round(diag[lid].get("tag_affinity", 0) + tag_mismatch_penalty, 4)
                    elif prompt_tags and not engram_tags:
                        # Engram has no content tags but query has topic signal — mild penalty
                        score += tag_mismatch_penalty * 0.5
                    content_scored.append((lid, score))
                fused = sorted(content_scored, key=lambda x: x[1], reverse=True)
        except Exception:
            pass

    # 4. Apply category filter (check primary + junction table categories)
    if category_filter:
        from engrammar.core.db import get_connection
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

    # 4.5. Apply tag filter — checks engram_tags table (content tags)
    if tag_filter:
        required_tags = set(t.strip().lower() for t in (tag_filter if isinstance(tag_filter, list) else [tag_filter]))
        from engrammar.core.db import get_content_tags_batch
        candidate_ids = [lid for lid, _ in fused if lid in engram_map]
        content_tags_map = get_content_tags_batch(candidate_ids, db_path=db_path)
        fused = [
            (lid, score) for lid, score in fused
            if lid in engram_map and required_tags.issubset(set(content_tags_map.get(lid, [])))
        ]

    # 5. Take top_k results
    results = []
    for engram_id, score in fused[:top_k]:
        if engram_id in engram_map:
            result = dict(engram_map[engram_id])
            result["score"] = round(score, 4)
            results.append(result)

    # 5.3. Apply min_top1_score filter: if top-1 is below threshold, return nothing
    min_top1 = scoring_config.get("min_top1_score", 0.0)
    if min_top1 > 0 and results and results[0].get("score", 0) < min_top1:
        results = []

    # 5.5. Apply min score threshold for hook injection
    if enforce_prerequisites:
        min_score = config["hooks"].get("prerequisites_min_score", 0.02)
        if min_score:
            results = [r for r in results if r.get("score", 0) >= min_score]

    # Save last search for introspection
    _save_last_search(query, results)

    if return_diagnostics:
        # Attach per-result diagnostics and query-level metadata
        for r in results:
            r["_diag"] = diag.get(r["id"], {})
        meta = {
            "prompt_tags": [(t, round(s, 4)) for t, s in prompt_tags] if prompt_tags else [],
            "rrf_k": rrf_k,
            "abstained": False,
            "per_result": {r["id"]: diag.get(r["id"], {}) for r in results},
        }
        return results, meta

    return results



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


def search_for_tool_context(tool_name, tool_input, db_path=None, enforce_prerequisites=False, cwd=None):
    """Specialized search for PreToolUse hook.

    Builds a semantic query from tool name + input and runs hybrid search.
    Returns empty list if the tool context is too shallow for useful search.

    Args:
        tool_name: name of the tool being used
        tool_input: dict of tool parameters
        enforce_prerequisites: if True, apply min_score_prompt threshold

    Returns:
        list of matching engrams (top 2)
    """
    config = load_config()
    max_results = config["display"]["max_engrams_per_tool"]

    query = _build_tool_query(tool_name, tool_input)
    if not query:
        return []
    results = search(
        query,
        top_k=max_results,
        db_path=db_path,
        enforce_prerequisites=enforce_prerequisites,
        cwd=cwd,
    )

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
