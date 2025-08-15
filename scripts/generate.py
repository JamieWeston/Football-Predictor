"""
Generate predictions and simple tips.

- Reads fixtures and team ratings
- Builds Poisson + Dixon–Coles score grids
- Outputs:
    data/predictions.json
    data/tips.json
    reports/PR_BODY.md

Safe to run as a module (python -m scripts.generate) or as a script.
"""

import os
import json
from datetime import datetime, timezone

# ---- Robust imports (works both as module and plain script) ----
try:
    from .model import PoissonDC
    from .sources import load_fixtures, load_team_ratings, fetch_best_odds
except ImportError:  # fallback if executed as plain script
    from scripts.model import PoissonDC
    from scripts.sources import load_fixtures, load_team_ratings, fetch_best_odds

# ---- Paths ----
THIS_DIR = os.path.dirname(__file__)
OUT_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "data"))
REP_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "reports"))

EDGE_THRESHOLD = 0.02  # 2% relative edge to surface a tip


def main() -> None:
    # Ensure output folders exist
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(REP_DIR, exist_ok=True)

    # Load inputs
    fixtures = load_fixtures()          # list of {match_id, kickoff_utc, home, away}
    ratings = load_team_ratings()       # dict team -> z-rating
    model = PoissonDC()                 # Poisson + Dixon–Coles

    # ---- Build predictions ----
    predictions = []
    for fx in fixtures:
        home, away = fx["home"], fx["away"]
        r_h = ratings.get(home, 0.0)
        r_a = ratings.get(away, 0.0)

        M, lam, mu = model.build_grid(r_h, r_a)
        pH, pD, pA = model.probs_from_grid(M)
        btts_y, btts_n, over25, under25 = model.btts_over_under_from_grid(M)
        ex_h, ex_a = model.expected_goals_from_grid(M)

        predictions.append({
            "match_id": fx["match_id"],
            "home": home,
            "away": away,
            "kickoff_utc": fx["kickoff_utc"],
            "probs": {"home": round(pH, 4), "draw": round(pD, 4), "away": round(pA, 4)},
            "btts": {"yes": round(btts_y, 4), "no": round(btts_n, 4)},
            "totals_2_5": {"over": round(over25, 4), "under": round(under25, 4)},
            "xg": {"home": round(ex_h, 3), "away": round(ex_a, 3)},
            "model_version": "poisson_dc_v1"
        })

    # ---- Optional odds → tips (if an odds API is configured) ----
    odds = fetch_best_odds()  # list of {match_id, market, selection, decimal_odds, source, fetched_utc}

    tips = []
    for pred in predictions:
        mid = pred["match_id"]
        # Model lines in a common format
        model_lines = {
            ("1X2", "Home"): pred["probs"]["home"],
            ("1X2", "Draw"): pred["probs"]["draw"],
            ("1X2", "Away"): pred["probs"]["away"],
            ("BTTS", "Yes"): pred["btts"]["yes"],
            ("BTTS", "No"):  pred["btts"]["no"],
            ("O2.5", "Over"): pred["totals_2_5"]["over"],
            ("O2.5", "Under"): pred["totals_2_5"]["under"],
        }

        market_rows = [o for o in odds if o.get("match_id") == mid]
        best_edge = None
        best_row = None

        for o in market_rows:
            key = (o.get("market"), o.get("selection"))
            if key not in model_lines:
                continue
            p = float(model_lines[key])
            if p <= 0.0 or p >= 1.0:
                continue
            fair = 1.0 / p
            dec = float(o["decimal_odds"])
            edge = (dec - fair) / fair  # relative edge
            if (best_edge is None) or (edge > best_edge):
                best_edge = edge
                best_row = o

        if best_row is not None and best_edge is not None and best_edge >= EDGE_THRESHOLD:
            tips.append({
                "match_id": mid,
                "home": pred["home"],
                "away": pred["away"],
                "tip": {"market": best_row["market"], "selection": best_row["selection"]},
                "model_prob": round(model_lines[(best_row["market"], best_row["selection"])], 4),
                "book_odds": float(best_row["decimal_odds"]),
                "source": best_row.get("source", ""),
                "edge_pct": round(best_edge * 100.0, 1)
            })
        else:
            tips.append({
                "match_id": mid,
                "home": pred["home"],
                "away": pred["away"],
                "tip": {"market": "None", "selection": "No Bet"},
                "model_prob": None,
                "book_odds": None,
                "source": "",
                "edge_pct": 0.0
            })

    # ---- Write outputs ----
    generated = datetime.now(timezone.utc).isoformat()

    with open(os.path.join(OUT_DIR, "predictions.json"), "w") as f:
        json.dump({"generated_utc": generated, "predictions": predictions}, f, indent=2)

    with open(os.path.join(OUT_DIR, "tips.json"), "w") as f:
        json.dump({"generated_utc": generated,
                   "rules": {"edge_threshold_pct": EDGE_THRESHOLD * 100.0},
                   "tips": tips}, f, indent=2)

    # ---- PR body for the GitHub Action ----
    with open(os.path.join(REP_DIR, "PR_BODY.md"), "w") as f:
        f.write("# Weekly predictions update\n\n")
        f.write(f"Generated: {generated}\n\n")
        f.write("## Tips\n")
        for t in tips:
            line = f"- **{t['home']} vs {t['away']}** — {t['tip']['market']} / {t['tip']['selection']}"
            if t["model_prob"] is not None:
                line += f" (model {t['model_prob']:.0%}, odds {t['book_odds']}, edge {t['edge_pct']:.1f}%)"
            f.write(line + "\n")


if __name__ == "__main__":
    main()
