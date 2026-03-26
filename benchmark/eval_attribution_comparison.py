#!/usr/bin/env python3
"""
Analyze potential improvement from weighted sigmoid attribution.
Measures:
1. How much signal is concentrated on tags that were shown
2. Current signal distribution vs potential with attribution weights
3. Impact of filter threshold on recovery rate
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List
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

def analyze_tag_relevance(db_path: str) -> dict:
    """
    Analyze current tag relevance distribution.
    Shows:
    - Tags with most positive vs negative signal
    - Distribution of eval counts (1, 2, 3+ evals per tag)
    - Potential recovery rates at different filter thresholds
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            tag,
            COUNT(*) as total_rows,
            COUNT(CASE WHEN score > 0 THEN 1 END) as positive_count,
            COUNT(CASE WHEN score < 0 THEN 1 END) as negative_count,
            COUNT(CASE WHEN score = 0 THEN 1 END) as neutral_count,
            SUM(positive_evals) as total_positive_evals,
            SUM(negative_evals) as total_negative_evals,
            AVG(score) as avg_score,
            SUM(ABS(score)) as total_signal
        FROM engram_tag_relevance
        GROUP BY tag
        ORDER BY total_signal DESC
    """)

    tags = [dict(row) for row in cursor.fetchall()]

    # Eval count distribution
    cursor.execute("""
        SELECT
            (positive_evals + negative_evals) as eval_count,
            COUNT(*) as count,
            SUM(positive_evals) as pos_evals,
            SUM(negative_evals) as neg_evals
        FROM engram_tag_relevance
        WHERE positive_evals + negative_evals > 0
        GROUP BY eval_count
        ORDER BY eval_count
    """)

    eval_dist = [dict(row) for row in cursor.fetchall()]

    # Recovery potential: tags with negative score but multiple positive evals
    cursor.execute("""
        SELECT
            COUNT(*) as total_negative_scored,
            SUM(CASE WHEN positive_evals >= 1 THEN 1 ELSE 0 END) as had_positive_eval,
            SUM(CASE WHEN positive_evals >= 2 THEN 1 ELSE 0 END) as had_2_positive_evals,
            SUM(CASE WHEN positive_evals >= positive_evals AND negative_evals <= 1 THEN 1 ELSE 0 END) as likely_recoverable
        FROM engram_tag_relevance
        WHERE score < -0.1
    """)

    recovery_data = dict(cursor.fetchone())

    conn.close()

    return {
        "timestamp": datetime.now().isoformat(),
        "top_10_tags_by_signal": [
            {
                "tag": t["tag"],
                "total_signal": round(t["total_signal"], 3),
                "avg_score": round(t["avg_score"], 3),
                "pos_evals": t["total_positive_evals"],
                "neg_evals": t["total_negative_evals"],
                "pos_rows": t["positive_count"],
                "neg_rows": t["negative_count"],
            }
            for t in tags[:10]
        ],
        "eval_distribution": [
            {
                "eval_count": r["eval_count"],
                "tags_with_count": r["count"],
                "total_positive": r["pos_evals"],
                "total_negative": r["neg_evals"],
            }
            for r in eval_dist
        ],
        "recovery_analysis": {
            "total_negatively_scored_tags": recovery_data["total_negative_scored"],
            "had_any_positive_eval": recovery_data["had_positive_eval"],
            "had_2_positive_evals": recovery_data["had_2_positive_evals"],
            "likely_recoverable": recovery_data["likely_recoverable"],
        },
        "filter_threshold_impact": {
            "threshold_3": "current — only filter after 3 evals",
            "threshold_2": f"would filter {recovery_data['had_positive_eval'] * 0.3:.0f} additional tags earlier",
            "threshold_1": f"would filter {recovery_data['had_positive_eval']:.0f} tags on first negative eval — risky",
        },
    }

def main():
    db_path = Path.home() / ".engrammar" / "engrams.db"
    results = analyze_tag_relevance(str(db_path))

    print(json.dumps(results, indent=2))

    # Save results
    out_path = Path(__file__).parent / f"eval_attribution_analysis_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")

if __name__ == "__main__":
    main()
