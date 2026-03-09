#!/usr/bin/env python3
"""Evaluate different scoring weight configurations.

Runs searches with varying semantic/tag weight blends and dumps comparison data.
Usage: PYTHONPATH=~/.engrammar ~/.engrammar/venv/bin/python scripts/eval_tag_penalty.py
"""

import json
import os
import sys

ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

import numpy as np

from engrammar.core.db import get_all_active_engrams, get_tag_relevance_with_evidence, get_connection
from engrammar.core.embeddings import embed_text, load_index, load_tag_index, vector_search
from engrammar.search.engine import _tokenize, _reciprocal_rank_fusion
from engrammar.search.environment import detect_environment


def get_per_tag_detail(engram_id):
    """Get per-tag relevance breakdown for an engram."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT tag, score, positive_evals, negative_evals FROM engram_tag_relevance WHERE engram_id = ?",
        (engram_id,),
    ).fetchall()
    conn.close()
    detail = {r["tag"]: [round(r["score"], 3), r["positive_evals"], r["negative_evals"]] for r in rows}
    return dict(sorted(detail.items(), key=lambda x: x[1][0], reverse=True))

# Weight configs to compare: (label, weight_semantic, weight_tag)
CONFIGS = [
    ("sem=0.60 tag=0.40", 0.60, 0.40),
    ("sem=0.70 tag=0.30", 0.70, 0.30),
    ("sem=0.80 tag=0.20", 0.80, 0.20),
    ("sem=0.50 tag=0.50", 0.50, 0.50),
]

# Test queries spanning different domains
QUERIES = [
    # Should match in engrammar repo (Python)
    "extraction pipeline engram processing",
    "daemon socket search",
    "tag relevance prerequisites",
    # Should NOT match well (frontend/React domain)
    "react component rendering hooks useState",
    "apollo graphql mutation cache update",
    "cypress testing selector best practices",
    # Generic (could go either way)
    "git commit conventions workflow",
    "refactor rename function",
    "fix bug in test",
]


def compute_base_rrf(engrams, query):
    """Run vector + BM25 and return RRF-fused scores (no tag penalty)."""
    engram_map = {e["id"]: e for e in engrams}

    # Vector search
    vector_results = []
    try:
        query_embedding = embed_text(query)
        embeddings, ids = load_index()
        if embeddings is not None:
            vector_results = vector_search(query_embedding, embeddings, ids, top_k=10)
    except Exception:
        pass

    # BM25
    corpus = [_tokenize(e["text"] + " " + e.get("category", "")) for e in engrams]
    from rank_bm25 import BM25Okapi
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
        key=lambda x: x[1], reverse=True,
    )[:10]

    rrf_k = max(1, len(engrams) // 5)
    fused = _reciprocal_rank_fusion([vector_results, bm25_ranked], k=rrf_k)
    return fused, engram_map


def apply_weighted_blend(fused, engram_map, env_tag_emb, tag_sim_map, w_semantic, w_tag):
    """Normalize RRF scores and blend with tag similarity using given weights."""
    # Normalize RRF to 0-1
    max_rrf = fused[0][1] if fused else 1.0
    blended = []
    for lid, score in fused:
        rrf_norm = score / max_rrf
        sim = tag_sim_map.get(lid)
        if sim is None:
            tag_norm = 0.5  # neutral for untagged
        else:
            tag_norm = max(0.0, min(1.0, (sim - 0.65) / 0.30))
        final = w_semantic * rrf_norm + w_tag * tag_norm
        blended.append((lid, final, sim, tag_norm))
    blended.sort(key=lambda x: x[1], reverse=True)
    return blended


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate tag penalty configurations")
    parser.add_argument("--tags", nargs="+", help="Override environment tags")
    parser.add_argument("--repo", help="Override repo name")
    parser.add_argument("--output", "-o", help="Output JSON path (default: eval_results.json in task dir)")
    return parser.parse_args()


def main():
    args = parse_args()
    env = detect_environment()

    if args.tags:
        env["tags"] = args.tags
    if args.repo:
        env["repo"] = args.repo
        # Also add repo tag
        env["tags"] = [t for t in env.get("tags", []) if not t.startswith("repo:")] + [f"repo:{args.repo}"]

    env_tags = env.get("tags", [])
    print(f"Environment tags: {env_tags}")
    print(f"Repo: {env.get('repo')}\n")

    engrams = get_all_active_engrams()
    print(f"Total engrams: {len(engrams)}\n")

    # Precompute tag similarity map
    env_tag_emb = embed_text(" ".join(env_tags))
    tag_embeddings, tag_ids = load_tag_index()

    tag_sim_map = {}
    if tag_embeddings is not None:
        env_norm = env_tag_emb / (np.linalg.norm(env_tag_emb) + 1e-10)
        tag_norms = np.linalg.norm(tag_embeddings, axis=1, keepdims=True) + 1e-10
        tag_emb_norm = tag_embeddings / tag_norms
        all_sims = tag_emb_norm @ env_norm
        tag_sim_map = {int(tag_ids[i]): float(all_sims[i]) for i in range(len(tag_ids))}

    results = {}

    for query in QUERIES:
        fused, engram_map = compute_base_rrf(engrams, query)
        query_results = {}

        for label, w_sem, w_tag in CONFIGS:
            blended = apply_weighted_blend(fused, engram_map, env_tag_emb, tag_sim_map, w_sem, w_tag)

            # Also apply tag relevance filter (same as engine.py)
            filtered = []
            for lid, score, sim, tag_norm in blended:
                avg_rel, total_evals = get_tag_relevance_with_evidence(lid, env_tags)
                if total_evals >= 3 and avg_rel < -0.1:
                    continue
                score += (avg_rel / 3.0) * 0.05
                filtered.append((lid, score, sim, tag_norm, avg_rel, total_evals))

            top5 = []
            for lid, score, sim, tag_norm, avg_rel, total_evals in filtered[:5]:
                e = engram_map.get(lid)
                if not e:
                    continue
                prereqs = e.get("prerequisites", "")
                if prereqs and isinstance(prereqs, str):
                    try:
                        prereqs = json.loads(prereqs)
                    except Exception:
                        prereqs = {}
                etags = prereqs.get("tags", []) if isinstance(prereqs, dict) else []

                top5.append({
                    "id": lid,
                    "text": e["text"][:90],
                    "score": round(score, 5),
                    "tag_sim": round(sim, 3) if sim is not None else None,
                    "tag_norm": round(tag_norm, 3),
                    "tag_rel": round(avg_rel, 2),
                    "tag_evals": total_evals,
                    "engram_tags": etags,
                    "tag_detail": get_per_tag_detail(lid),
                })

            query_results[label] = top5

        results[query] = query_results

    # Dump to file
    default_out = os.path.join(os.path.dirname(__file__), "..", "tasks", "open", "[1]-018-widen-tag-penalty", "eval_results.json")
    out_path = args.output or default_out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    class CompactArrayEncoder(json.JSONEncoder):
        """Keep short arrays on one line."""
        def encode(self, o):
            return self._encode(o, indent_level=0)

        def _encode(self, o, indent_level):
            if isinstance(o, list) and all(isinstance(x, (int, float)) for x in o):
                return json.dumps(o)
            if isinstance(o, dict):
                if not o:
                    return "{}"
                indent = "  " * (indent_level + 1)
                closing = "  " * indent_level
                items = []
                for k, v in o.items():
                    items.append(f'{indent}{json.dumps(k)}: {self._encode(v, indent_level + 1)}')
                return "{\n" + ",\n".join(items) + f"\n{closing}}}"
            if isinstance(o, list):
                if not o:
                    return "[]"
                indent = "  " * (indent_level + 1)
                closing = "  " * indent_level
                items = [f"{indent}{self._encode(x, indent_level + 1)}" for x in o]
                return "[\n" + ",\n".join(items) + f"\n{closing}]"
            return json.dumps(o)

    with open(out_path, "w") as f:
        f.write(CompactArrayEncoder().encode(results))
        f.write("\n")
    print(f"Wrote: {out_path}\n")

    # Print readable comparison
    for query, configs in results.items():
        print(f"{'='*100}")
        print(f"QUERY: {query}")
        print(f"{'='*100}")
        for label, top5 in configs.items():
            print(f"\n  [{label}]")
            for i, r in enumerate(top5[:3]):
                tag_info = f"sim={r['tag_sim']} tn={r['tag_norm']}" if r['tag_sim'] is not None else "no-tags tn=0.500"
                print(f"    #{i+1} EG#{r['id']} score={r['score']:.5f} {tag_info} | {r['text'][:70]}")
                if r.get("tag_detail"):
                    for tag, (sc, pos, neg) in r["tag_detail"].items():
                        print(f"         {tag:30s} {sc:+.3f}  (+{pos}/-{neg})")
        print()


if __name__ == "__main__":
    main()
