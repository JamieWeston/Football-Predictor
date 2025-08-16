# scripts/generate.py
"""
Generate predictions and simple tips.

- Reads fixtures and team ratings (from scripts.sources)
- Builds Poisson + Dixon–Coles score grids (from scripts.model)
- Outputs:
    data/predictions.json
    data/tips.json
    reports/PR_BODY.md

Safe to run as a module (python -m scripts.generate) or as a script.
"""

import os
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple

import numpy as np

# Robust imports so it works both as a module and a script
try:
    from .model import PoissonDC
    from .sources import load_fixtures, load_team_ratings
except ImportError:
    from scripts.model import PoissonDC
    from scripts.sources import load_fixtures, load_team_ratings


ROOT = os.path.dirname(os.path.dirname(__file__))
OUT_DIR = os.path.join(ROOT, "data")
REP_DIR = os.path.join(ROOT, "reports")


def top_scorelines(M: np.ndarray, k: int = 3) -> List[Dict[str, Any]]:
    """
    Return top-k most likely scorelines from a probability grid M[i,j] = P(i,j).
    """
    flat_idx = np.argsort(M.ravel())[::-1][:k]
    out = []
    for idx in flat_idx:
        i, j = np.unravel_index(idx, M.shape)
        out.append({"home_goals": int(i), "away_goals": int(j), "prob": float(M[i, j])})
    return out


def pick_primary_tip(prob_home: float, prob_draw: float, prob_away: float) -> Tuple[str, str, float]:
    """
    Choose the most likely 1X2 outcome.
    Returns (market, selection, prob)
    """
    vals = [("Home", prob_home), ("Draw", prob_draw), ("Away", prob_away)]
    sel, p = max(vals, key=lambda x: x[1])
    return "1X2", sel, p


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(REP_DIR, exist_ok=True)

    # Load data
    fixtures = load_fixtures()            # expected to respect FD_WINDOW_DAYS env inside the loader
    ratings = load_team_ratings()         # team -> rating float
    model = PoissonDC()

    predictions: List[Dict[str, Any]] = []
    tips: List[Dict[str, Any]] = []

    for fx in fixtures:
        h = fx["home"]
        a = fx["away"]
        r_h = ratings.get(h, 0.0)
        r_a = ratings.get(a, 0.0)

        # Build match grid and features
        M, lam, mu = model.build_grid(r_h, r_a)
        pH, pD, pA = model.probs_from_grid(M)
        btts_y, btts_n, over25, under25 = model.btts_over_under_from_grid(M)
        ex_h, ex_a = model.expected_goals_from_grid(M)
        score_tops = top_scorelines(M, k=3)

        # Store full prediction row
        predictions.append({
            "match_id": fx["match_id"],
            "home": h,
            "away": a,
            "kickoff_utc": fx["kickoff_utc"],
            "probs": {"home": round(pH, 4), "draw": round(pD, 4), "away": round(pA, 4)},
            "btts": {"yes": round(btts_y, 4), "no": round(btts_n, 4)},
            "totals_2_5": {"over": round(over25, 4), "under": round(under25, 4)},
            "xg": {"home": round(ex_h, 3), "away": round(ex_a, 3)},
            "scorelines_top": [
                {"home_goals": s["home_goals"], "away_goals": s["away_goals"], "prob": round(s["prob"], 4)}
                for s in score_tops
            ],
            "model_version": "poisson_dc_v1"
        })

        # Choose a simple primary tip: most-likely 1X2 outcome
        market, selection, p_sel = pick_primary_tip(pH, pD, pA)

        # Useful alternates for UI (and PR body)
        alts = [
            {"market": "BTTS", "selection": "Yes", "prob": round(btts_y, 4)},
            {"market": "O2.5", "selection": "Over", "prob": round(over25, 4)},
        ]
        # Add most-likely correct score
        if score_tops:
            best = score_tops[0]
            alts.append({
                "market": "CorrectScore",
                "selection": f"{best['home_goals']}-{best['away_goals']}",
                "prob": round(best["prob"], 4)
            })

        tips.append({
            "match_id": fx["match_id"],
            "home": h,
            "away": a,
            "tip": {"market": market, "selection": selection},
            "model_prob": round(p_sel, 4),
            "alts": alts
        })

    # Write JSON outputs
    generated_ts = datetime.now(timezone.utc).isoformat()

    with open(os.path.join(OUT_DIR, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_utc": generated_ts, "predictions": predictions}, f, indent=2)

    with open(os.path.join(OUT_DIR, "tips.json"), "w", encoding="utf-8") as f:
        json.dump({
            "generated_utc": generated_ts,
            "rules": {"tip_policy": "most_likely_1x2", "alts": ["BTTS Yes", "Over 2.5", "Best Correct Score"]},
            "tips": tips
        }, f, indent=2)

    # Compose a clean PR body (no escaping issues)
    pr_lines: List[str] = []
    pr_lines.append("# Weekly predictions update\n")
    pr_lines.append(f"Generated: {generated_ts}\n")
    pr_lines.append("## Tips")

    def _format_tip_row(t: Dict[str, Any]) -> str:
        line = f"- **{t['home']} vs {t['away']}** — {t['tip']['market']} / {t['tip']['selection']} (model {t['model_prob']:.0%})"
        alts = t.get("alts", [])
        if alts:
            alts_str = ", ".join([f"{a['market']} {a['selection']} {a['prob']:.0%}" for a in alts])
            line += f" | Alts: {alts_str}"
        return line

    for t in tips:
        pr_lines.append(_format_tip_row(t))

    with open(os.path.join(REP_DIR, "PR_BODY.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(pr_lines) + "\n")

    # Log a short summary for Actions logs
    print(f"[generate] wrote {len(predictions)} predictions and {len(tips)} tips")
    if predictions:
        print(f"[generate] first fixture: {predictions[0]['home']} vs {predictions[0]['away']}")


if __name__ == "__main__":
    main()
