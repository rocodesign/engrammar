#!/usr/bin/env python3
"""Evaluate threshold and RELEVANCE_WEIGHT tuning.

Simulates searches with different threshold combos to find optimal values.
Usage: PYTHONPATH=~/.engrammar ~/.engrammar/venv/bin/python scripts/eval_thresholds.py
"""

import json
import os
import sys

ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

import numpy as np
from rank_bm25 import BM25Okapi

from engrammar.core.db import get_all_active_engrams, get_tag_relevance_with_evidence, get_connection
from engrammar.core.embeddings import embed_text, load_index, load_tag_index, vector_search
from engrammar.search.engine import _tokenize, _reciprocal_rank_fusion
from engrammar.search.environment import detect_environment


# ─── Threshold configs to compare ───
RELEVANCE_WEIGHTS = [0.02, 0.05, 0.08, 0.10]
MIN_SCORE_PREREQS = [0.20, 0.25, 0.30, 0.35, 0.40]
MIN_SCORE_TOOL = [0.25, 0.30, 0.35, 0.40, 0.45]

# Blend weights (fixed from #018)
W_SEMANTIC = 0.60
W_TAG = 0.40

# ─── Test scenarios ───
SCENARIOS = {
    "engrammar": {
        "tags": ["python", "repo:engrammar", "engrammar", "shell"],
        "queries": {
            # Should match well (in-domain)
            "extraction pipeline engram processing": {"expect": "high", "note": "core engrammar feature"},
            "daemon socket search": {"expect": "high", "note": "engrammar daemon"},
            "tag relevance prerequisites": {"expect": "high", "note": "engrammar scoring"},
            "python import module structure": {"expect": "medium", "note": "general python"},
            # Should match poorly (wrong domain)
            "react component rendering hooks useState": {"expect": "low", "note": "frontend/React"},
            "cypress testing selector best practices": {"expect": "low", "note": "frontend testing"},
            "jira ticket workflow automation": {"expect": "low", "note": "project management"},
        },
    },
    "staff-portal": {
        "tags": ["docker", "frontend", "github", "jest", "monorepo", "react",
                 "repo:staff-portal", "testing", "typescript"],
        "queries": {
            # Should match well (in-domain)
            "react component testing jest": {"expect": "high", "note": "frontend testing"},
            "typescript interface prop types": {"expect": "high", "note": "TS patterns"},
            "git commit conventions workflow": {"expect": "medium", "note": "general git"},
            "pull request review description": {"expect": "medium", "note": "git workflow"},
            # Should match poorly (wrong domain)
            "python daemon socket processing": {"expect": "low", "note": "Python backend"},
            "extraction pipeline engram": {"expect": "low", "note": "engrammar internals"},
            "ruby rails migration database": {"expect": "low", "note": "Ruby/Rails"},
        },
    },
}


def compute_base_pipeline(engrams, query, env_tags):
    """Run full pipeline up to blending, return blended scores + metadata."""
    engram_map = {e["id"]: e for e in engrams}

    # Vector search
    vector_results = []
    try:
        query_embedding = embed_text(query)
        embeddings, ids = load_index()
        if embeddings is not None:
            vector_results = vector_search(query_embedding, embeddings, ids, top_k=10)
            allowed_ids = set(engram_map.keys())
            vector_results = [(lid, s) for lid, s in vector_results if lid in allowed_ids]
    except Exception:
        pass

    # BM25
    corpus = [_tokenize(e["text"] + " " + e.get("category", "")) for e in engrams]
    bm25 = BM25Okapi(corpus)
    query_tokens = _tokenize(query)
    bm25_scores = bm25.get_scores(query_tokens)
    query_token_set = set(query_tokens)
    bm25_ranked = sorted(
        [(engrams[i]["id"], float(bm25_scores[i]))
         for i in range(len(engrams))
         if query_token_set.intersection(corpus[i])],
        key=lambda x: x[1], reverse=True,
    )[:10]

    # RRF
    rrf_k = max(1, len(engrams) // 5)
    fused = _reciprocal_rank_fusion([vector_results, bm25_ranked], k=rrf_k)

    # Normalize RRF
    max_rrf = fused[0][1] if fused else 1.0
    fused = [(lid, score / max_rrf) for lid, score in fused]

    # Tag similarity
    env_tag_emb = embed_text(" ".join(env_tags))
    tag_embeddings, tag_ids = load_tag_index()
    tag_sim_map = {}
    if tag_embeddings is not None:
        env_norm = env_tag_emb / (np.linalg.norm(env_tag_emb) + 1e-10)
        tag_norms = np.linalg.norm(tag_embeddings, axis=1, keepdims=True) + 1e-10
        tag_emb_norm = tag_embeddings / tag_norms
        all_sims = tag_emb_norm @ env_norm
        tag_sim_map = {int(tag_ids[i]): float(all_sims[i]) for i in range(len(tag_ids))}

    # Blend
    blended = []
    for lid, rrf_norm in fused:
        sim = tag_sim_map.get(lid)
        if sim is None:
            tag_norm = 0.5
        else:
            tag_norm = max(0.0, min(1.0, (sim - 0.65) / 0.30))
        final = W_SEMANTIC * rrf_norm + W_TAG * tag_norm
        blended.append({
            "id": lid,
            "rrf_norm": rrf_norm,
            "tag_sim": sim,
            "tag_norm": tag_norm,
            "blended": final,
            "text": engram_map.get(lid, {}).get("text", "")[:80],
        })

    blended.sort(key=lambda x: x["blended"], reverse=True)
    return blended, engram_map


def apply_relevance_filter(blended, env_tags, relevance_weight, neg_threshold=-0.1, min_evals=3):
    """Apply tag relevance filter + boost with given weight."""
    filtered = []
    for item in blended:
        avg_score, total_evals = get_tag_relevance_with_evidence(item["id"], env_tags)
        if total_evals >= min_evals and avg_score < neg_threshold:
            continue
        score = item["blended"] + (avg_score / 3.0) * relevance_weight
        filtered.append({**item, "final_score": score, "tag_rel": avg_score, "tag_evals": total_evals})
    filtered.sort(key=lambda x: x["final_score"], reverse=True)
    return filtered


def apply_min_score(results, min_score):
    """Apply minimum score threshold."""
    return [r for r in results if r["final_score"] >= min_score]


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate threshold configurations")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()), help="Run single scenario")
    parser.add_argument("--output", "-o", help="Output JSON path")
    return parser.parse_args()


def main():
    args = parse_args()
    engrams = get_all_active_engrams()
    print(f"Total engrams: {len(engrams)}\n")

    scenarios = {args.scenario: SCENARIOS[args.scenario]} if args.scenario else SCENARIOS

    all_results = {}

    for scenario_name, scenario in scenarios.items():
        env_tags = scenario["tags"]
        print(f"{'='*100}")
        print(f"SCENARIO: {scenario_name}")
        print(f"Tags: {env_tags}")
        print(f"{'='*100}\n")

        scenario_results = {}

        for query, meta in scenario["queries"].items():
            blended, engram_map = compute_base_pipeline(engrams, query, env_tags)

            print(f"  QUERY: {query}  [expect: {meta['expect']}] — {meta['note']}")
            print(f"  {'─'*90}")

            query_results = {}

            # Test each RELEVANCE_WEIGHT
            for rw in RELEVANCE_WEIGHTS:
                filtered = apply_relevance_filter(blended, env_tags, rw)
                top3 = filtered[:3]

                # Test min_score thresholds (for prompt hook)
                for ms in MIN_SCORE_PREREQS:
                    after_threshold = apply_min_score(filtered, ms)
                    key = f"rw={rw:.2f} min={ms:.2f}"
                    query_results[key] = {
                        "count_before_threshold": len(filtered),
                        "count_after_threshold": len(after_threshold),
                        "top3": [
                            {
                                "id": r["id"],
                                "score": round(r["final_score"], 4),
                                "rrf": round(r["rrf_norm"], 3),
                                "tag_norm": round(r["tag_norm"], 3),
                                "tag_rel": round(r["tag_rel"], 3),
                                "text": r["text"][:60],
                                "passes": r["final_score"] >= ms,
                            }
                            for r in top3
                        ],
                    }

            # Print summary for default config (rw=0.05, min=0.30)
            default = query_results.get("rw=0.05 min=0.30", {})
            top3 = default.get("top3", [])
            pass_count = sum(1 for r in top3 if r.get("passes"))
            print(f"  Default (rw=0.05 min=0.30): {pass_count}/{len(top3)} pass threshold")
            for r in top3:
                status = "PASS" if r.get("passes") else "FAIL"
                print(f"    [{status}] EG#{r['id']} score={r['score']:.4f} rrf={r['rrf']:.3f} tn={r['tag_norm']:.3f} rel={r['tag_rel']:+.3f} | {r['text'][:55]}")

            # Show what changes across RELEVANCE_WEIGHT values
            print(f"\n  Threshold sensitivity (top1 score at different rw/min combos):")
            print(f"  {'rw':>6s} | {'min=0.20':>8s} {'min=0.25':>8s} {'min=0.30':>8s} {'min=0.35':>8s} {'min=0.40':>8s}")
            print(f"  {'─'*6}-+-{'─'*8}-{'─'*8}-{'─'*8}-{'─'*8}-{'─'*8}")
            for rw in RELEVANCE_WEIGHTS:
                row = f"  {rw:6.2f} |"
                for ms in MIN_SCORE_PREREQS:
                    key = f"rw={rw:.2f} min={ms:.2f}"
                    data = query_results.get(key, {})
                    n_pass = data.get("count_after_threshold", 0)
                    top = data.get("top3", [{}])
                    top1_score = top[0].get("score", 0) if top else 0
                    row += f" {n_pass:2d}@{top1_score:.2f}"
                print(row)

            print()
            scenario_results[query] = query_results

        all_results[scenario_name] = scenario_results

    # Save full results
    out_path = args.output or os.path.join(os.path.dirname(__file__), "..", "eval_results", "threshold_eval.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nFull results: {out_path}")


if __name__ == "__main__":
    main()
