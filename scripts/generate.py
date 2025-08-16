# scripts/generate.py
import os, json
from datetime import datetime, timezone

from scripts.model import PoissonDC
from scripts.sources import load_fixtures, load_team_strengths
from scripts.team_names import norm

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
REP_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

def most_likely_1x2(probs):
    items = [("Home", probs["home"]), ("Draw", probs["draw"]), ("Away", probs["away"])]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[0]

def main():
    os.makedirs(OUT_DIR, exist_ok=True); os.makedirs(REP_DIR, exist_ok=True)

    fixtures = load_fixtures()
    strengths = load_team_strengths()
    model = PoissonDC()

    predictions, tips = [], []

    for fx in fixtures:
        h, a = fx["home"], fx["away"]
        hn, an = norm(h), norm(a)

        sh = strengths.get(hn, {"attack": 0.0, "defence": 0.0, "home_adv": 0.20})
        sa = strengths.get(an, {"attack": 0.0, "defence": 0.0, "home_adv": 0.20})

        lam, mu = model.rates_from_features(
            atk_h=sh["attack"], def_h=sh["defence"], ha_h=sh["home_adv"],
            atk_a=sa["attack"], def_a=sa["defence"]
        )
        M = model.build_grid(lam, mu)

        pH, pD, pA = model.probs_from_grid(M)
        btts_y, btts_n, over25, under25 = model.btts_over_under_from_grid(M)
        ex_h, ex_a = model.expected_goals_from_grid(M)
        top_scores = model.top_scorelines(M, k=3)

        pred = {
            "match_id": fx["match_id"], "fd_id": fx.get("fd_id", ""),
            "home": h, "away": a, "kickoff_utc": fx["kickoff_utc"],
            "probs": {"home": round(pH,4), "draw": round(pD,4), "away": round(pA,4)},
            "btts": {"yes": round(btts_y,4), "no": round(btts_n,4)},
            "totals_2_5": {"over": round(over25,4), "under": round(under25,4)},
            "xg": {"home": round(lam,2), "away": round(mu,2)},   # model rates as pre-match xG
            "scorelines_top": [{"home_goals": s["home_goals"], "away_goals": s["away_goals"], "prob": round(s["prob"],4)} for s in top_scores],
            "model_version": "poisson_dc_xg_v2"
        }
        predictions.append(pred)

        pick, p_pick = most_likely_1x2(pred["probs"])
        tips.append({
            "match_id": fx["match_id"], "home": h, "away": a,
            "tip": {"market": "1X2", "selection": pick},
            "model_prob": round(p_pick,4),
            "alternatives": []
        })

    ts = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(OUT_DIR, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_utc": ts, "predictions": predictions}, f, indent=2)
    with open(os.path.join(OUT_DIR, "tips.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_utc": ts, "rules": {"tip_policy":"1X2_max"}, "tips": tips}, f, indent=2)

    with open(os.path.join(REP_DIR, "PR_BODY.md"), "w", encoding="utf-8") as f:
        f.write("# Predictions update\n\n")
        f.write(f"Generated: {ts}\n\n")
        f.write("## Picks\n")
        for t in tips:
            f.write(f"- **{t['home']} vs {t['away']}** — 1X2 / {t['tip']['selection']} (model {t['model_prob']:.0%})\n")

if __name__ == "__main__":
    main()
