import os, json
from datetime import datetime, timezone
from collections import defaultdict

from scripts.model import PoissonDC
from scripts.sources import load_fixtures, load_team_ratings, fetch_best_odds

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
REP_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

def main():
    fixtures = load_fixtures()
    ratings = load_team_ratings()
    model = PoissonDC()

    predictions = []
    for fx in fixtures:
        h, a = fx["home"], fx["away"]
        r_h = ratings.get(h, 0.0)
        r_a = ratings.get(a, 0.0)
        M, lam, mu = model.build_grid(r_h, r_a)
        pH, pD, pA = model.probs_from_grid(M)
        btts_y, btts_n, over25, under25 = model.btts_over_under_from_grid(M)
        ex_h, ex_a = model.expected_goals_from_grid(M)
        predictions.append({
            "match_id": fx["match_id"], "home": h, "away": a, "kickoff_utc": fx["kickoff_utc"],
            "probs": {"home": round(pH,4), "draw": round(pD,4), "away": round(pA,4)},
            "btts": {"yes": round(btts_y,4), "no": round(btts_n,4)},
            "totals_2_5": {"over": round(over25,4), "under": round(under25,4)},
            "xg": {"home": round(ex_h,3), "away": round(ex_a,3)},
            "model_version": "poisson_dc_v1"
        })

    # Odds (optional)
    odds = fetch_best_odds()

    # If odds exist, compute simple edges and pick a best market; else, "No Bet"
    tips = []
    for pred in predictions:
        mid = pred["match_id"]
        # Build model probs dict in a common format
        model_lines = {
            ("1X2","Home"): pred["probs"]["home"],
            ("1X2","Draw"): pred["probs"]["draw"],
            ("1X2","Away"): pred["probs"]["away"],
            ("BTTS","Yes"): pred["btts"]["yes"],
            ("BTTS","No"):  pred["btts"]["no"],
            ("O2.5","Over"): pred["totals_2_5"]["over"],
            ("O2.5","Under"):pred["totals_2_5"]["under"],
        }
        market_rows = [o for o in odds if o.get("match_id")==mid]
        best_edge = None
        best_row = None
        for o in market_rows:
            key = (o["market"], o["selection"])
            if key not in model_lines: 
                continue
            p = model_lines[key]
            if p<=0 or p>=1: 
                continue
            fair = 1/p
            dec = float(o["decimal_odds"])
            edge = (dec - fair)/fair  # relative edge
            if (best_edge is None) or (edge > best_edge):
                best_edge = edge; best_row = o
        if best_row and best_edge is not None and best_edge >= 0.02:  # 2% threshold
            tips.append({
                "match_id": mid, "home": pred["home"], "away": pred["away"],
                "tip": {"market": best_row["market"], "selection": best_row["selection"]},
                "model_prob": round(model_lines[(best_row["market"], best_row["selection"])],4),
                "book_odds": best_row["decimal_odds"], "source": best_row.get("source",""),
                "edge_pct": round(best_edge*100,1)
            })
        else:
            tips.append({
                "match_id": mid, "home": pred["home"], "away": pred["away"],
                "tip": {"market":"None","selection":"No Bet"},
                "model_prob": None, "book_odds": None, "source": "",
                "edge_pct": 0.0
            })

    # Write outputs
    out_pred = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "predictions": predictions
    }
    with open(os.path.join(OUT_DIR, "predictions.json"), "w") as f:
        json.dump(out_pred, f, indent=2)

    out_tips = {
        "generated_utc": out_pred["generated_utc"],
        "rules": {"edge_threshold_pct": 2.0},
        "tips": tips
    }
    with open(os.path.join(OUT_DIR, "tips.json"), "w") as f:
        json.dump(out_tips, f, indent=2)

    # Quick PR body
    os.makedirs(REP_DIR, exist_ok=True)
    with open(os.path.join(REP_DIR, "PR_BODY.md"), "w") as f:
        f.write("# Weekly predictions update\n\n")
        f.write(f"Generated: {out_pred['generated_utc']}\n\n")
        f.write("## Tips\n")
        for t in tips:
            f.write(f"- **{t['home']} vs {t['away']}** — {t['tip']['market']} / {t['tip']['selection']}")
            if t["model_prob"] is not None:
                f.write(f" (model {t['model_prob']:.0%}, odds {t['book_odds']}, edge {t['edge_pct']:.1f}%)")
            f.write("\n")

if __name__ == "__main__":
    main()
