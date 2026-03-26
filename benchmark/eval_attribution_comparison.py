#!/usr/bin/env python3
"""
Compare old (simple avg) vs new (weighted sigmoid) attribution for evaluations.
Replays existing session_audit records, runs evaluator with both methods,
and measures improvement in per-tag signal accuracy.
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

def shifted_sigmoid_weight(sim: float, floor: float = 0.20, ceiling: float = 0.80) -> float:
    """
    Weight attribution by tag similarity using shifted sigmoid.
    floor=0.20: below this, weight is 0
    ceiling=0.80: above this, weight plateaus at 1.0
    """
    if sim < floor:
        return 0.0
    if sim > ceiling:
        return 1.0
    # Linear ramp from floor to ceiling
    return ((sim - floor) / (ceiling - floor)) ** 2

def old_attribution(tag_scores: Dict[str, float]) -> Dict[str, float]:
    """Old method: simple average across all tags."""
    if not tag_scores:
        return {}
    avg = sum(tag_scores.values()) / len(tag_scores)
    return {tag: avg for tag in tag_scores}

def new_attribution(
    engram_tags: List[str],
    tag_sims: Dict[str, float],
    eval_score: float,
    floor: float = 0.20
) -> Dict[str, float]:
    """
    New method: weighted by tag similarity.
    Only tags with sim >= floor get signal.
    """
    result = {}
    for tag in engram_tags:
        sim = tag_sims.get(tag, 0.0)
        if sim >= floor:
            weight = shifted_sigmoid_weight(sim, floor=floor)
            result[tag] = eval_score * weight
        else:
            result[tag] = 0.0
    return result

def load_audit_records(db_path: str, limit: int = 100) -> List[dict]:
    """Load sample session_audit records from DB."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id, engram_id, prompt_tags, engram_tags, engram_context,
            evaluation_score, evaluation_notes
        FROM session_audit
        WHERE evaluation_score IS NOT NULL
        LIMIT ?
    """, (limit,))

    records = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return records

def run_comparison(db_path: str, limit: int = 100) -> dict:
    """
    Compare old vs new attribution on existing evaluations.
    Returns metrics on signal distribution and tag coverage.
    """
    records = load_audit_records(db_path, limit)
    if not records:
        print(f"No evaluation records found in {db_path}")
        return {}

    results = {
        "total_records": len(records),
        "per_method": {
            "old": {"total_signal": 0, "tags_scored": 0, "tags_scored_above_zero": 0},
            "new": {"total_signal": 0, "tags_scored": 0, "tags_scored_above_zero": 0},
        },
        "tag_comparisons": {},
    }

    for record in records:
        engram_id = record["engram_id"]
        eval_score = record["evaluation_score"]

        # Parse JSON fields
        try:
            engram_tags = json.loads(record["engram_tags"]) if record["engram_tags"] else []
            engram_context = json.loads(record["engram_context"]) if record["engram_context"] else {}
            tag_sims = engram_context.get("tag_sims", {})
        except json.JSONDecodeError:
            continue

        # Compute old attribution (simple avg)
        tag_scores_for_avg = {tag: 1.0 for tag in engram_tags}  # Dummy scores for avg
        old_result = old_attribution(tag_scores_for_avg)
        old_attributed = {tag: eval_score * old_result[tag] for tag in engram_tags}

        # Compute new attribution (weighted sigmoid)
        new_attributed = new_attribution(engram_tags, tag_sims, eval_score)

        # Accumulate stats
        for tag in engram_tags:
            if tag not in results["tag_comparisons"]:
                results["tag_comparisons"][tag] = {
                    "count": 0,
                    "old_total": 0.0,
                    "new_total": 0.0,
                    "new_above_zero": 0,
                }

            old_score = old_attributed.get(tag, 0.0)
            new_score = new_attributed.get(tag, 0.0)

            results["tag_comparisons"][tag]["count"] += 1
            results["tag_comparisons"][tag]["old_total"] += abs(old_score)
            results["tag_comparisons"][tag]["new_total"] += abs(new_score)
            if new_score != 0:
                results["tag_comparisons"][tag]["new_above_zero"] += 1

            results["per_method"]["old"]["total_signal"] += abs(old_score)
            results["per_method"]["old"]["tags_scored"] += 1
            if old_score != 0:
                results["per_method"]["old"]["tags_scored_above_zero"] += 1

            results["per_method"]["new"]["total_signal"] += abs(new_score)
            results["per_method"]["new"]["tags_scored"] += 1
            if new_score != 0:
                results["per_method"]["new"]["tags_scored_above_zero"] += 1

    # Compute summary metrics
    results["metrics"] = {
        "signal_concentration_improvement": (
            results["per_method"]["new"]["tags_scored_above_zero"] /
            max(1, results["per_method"]["new"]["tags_scored"])
        ) - (
            results["per_method"]["old"]["tags_scored_above_zero"] /
            max(1, results["per_method"]["old"]["tags_scored"])
        ),
        "old_avg_signal_per_tag": (
            results["per_method"]["old"]["total_signal"] /
            max(1, results["per_method"]["old"]["tags_scored"])
        ),
        "new_avg_signal_per_tag": (
            results["per_method"]["new"]["total_signal"] /
            max(1, results["per_method"]["new"]["tags_scored"])
        ),
    }

    return results

if __name__ == "__main__":
    db_path = Path.home() / ".engrammar" / "engrammar.db"
    results = run_comparison(str(db_path), limit=200)

    print(json.dumps(results, indent=2))

    # Save results
    out_path = Path(__file__).parent / f"eval_attribution_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")
