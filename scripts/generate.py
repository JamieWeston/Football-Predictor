# scripts/generate.py
"""
Generate predictions and simple tips.

- Reads fixtures and team strengths
- Builds Poisson + Dixon–Coles score grids
- Outputs:
    data/predictions.json
    data/tips.json
    reports/PR_BODY.md

Safe to run as a module (python -m scripts.generate) or as a script.
"""
import os, json
from datetime import datetime, timezone

from scripts.model import PoissonDC
from scripts.sources import load_fixtures, load_team_strengths

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
REP_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

def main():
    # --- Inputs ---
    fixtures = load_fixtures()
    print(f"[generate] fixtures loaded: {len(fixtures)}")
    strengths = load_team_strengths()
    model = PoissonDC()

    predictions = []
    for fx in fixtures:
        h, a = fx["home"], fx["away"]
        r_h = strengths.get(h, 0.0)
        r_a = strengths.get(a, 0.0)

        M, lam, mu = model.build_grid(r_h, r_a)
        # warn if tiny combined rates (diagnostic)
        if lam + mu < 0.35:
            print(f"[warn] Very small rates for {h} vs {a}: lam={lam:.2f}, mu={mu:.2f} (check strengths/baseline)")

        pH, pD, pA = model.probs_from_grid(M)
        btts_y, btts_n, over25, under25 = model.btts_over_under_from_grid(M)
        ex_h, ex_a = model.expected_goals_from_grid(M)
        top_scores = model.top_scorelines(M, n=3)

        predictions.append({
            "match_id": f"{fx.get('kickoff_utc','')[:10].replace('-','_')}_{fx.get('fd_id','')}_{h[:3].upper()}-{a[:3].upper()}",
            "fd_id": fx.get("fd_id"),
            "home": h, "away": a, "kickoff_utc": fx["kickoff_utc"],
            "probs": {"home": round(pH,4), "draw": round(pD,4), "away": round(pA,4)},
            "btts": {"yes": round(btts_y,4), "no": round(btts_n,4)},
            "totals_2_5": {"over": round(over25,4), "under": round(under25,4)},
            "xg": {"home": round(ex_h,3), "away": round(ex_a,3)},
            "scorelines_top": top_scores,
            "model_version": "poisson_dc_v1"
        })

    # Simple "most likely" tips (no odds API)
    tips = []
    for pred in predictions:
        probs = pred["probs"]
        best_market = max(probs, key=probs.get)
        tips.append({
            "match_id": pred["match_id"], "home": pred["home"], "away": pred["away"],
            "tip": {"market":"1X2","selection": best_market.capitalize()},
            "model_prob": round(probs[best_market],4),
            "book_odds": None, "source": "",
            "edge_pct": None
        })

    # --- Outputs ---
    os.makedirs(OUT_DIR, exist_ok=True)
    out_pred = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "predictions": predictions
    }
    with open(os.path.join(OUT_DIR, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump(out_pred, f, indent=2)

    out_tips = {
        "generated_utc": out_pred["generated_utc"],
        "rules": {"note": "Tip = most likely 1X2 outcome by model probability"},
        "tips": tips
    }
    with open(os.path.join(OUT_DIR, "tips.json"), "w", encoding="utf-8") as f:
        json.dump(out_tips, f, indent=2)

    # PR body
    os.makedirs(REP_DIR, exist_ok=True)
    with open(os.path.join(REP_DIR, "PR_BODY.md"), "w", encoding="utf-8") as f:
        f.write("# Weekly predictions update\n\n")
        f.write(f"Generated: {out_pred['generated_utc']}\n\n")
        f.write(f"Fixtures: {len(predictions)}\n\n")
        f.write("## Picks (most likely 1X2)\n")
        for t in tips:
            f.write(f"- **{t['home']} vs {t['away']}** — 1X2 / {t['tip']['selection']} (model {t['model_prob']:.0%})\n")

if __name__ == "__main__":
    main()

