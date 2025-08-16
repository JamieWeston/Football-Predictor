# scripts/generate.py
import os, json
from datetime import datetime, timezone

from scripts.model import PoissonDC
from scripts.sources import load_fixtures, load_team_ratings, fetch_best_odds
from scripts.team_names import norm

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
REP_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

def most_likely_1x2(probs):
    items = [("Home", probs["home"]), ("Draw", probs["draw"]), ("Away", probs["away"])]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[0]

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(REP_DIR, exist_ok=True)

    fixtures = load_fixtures()
    ratings  = load_team_ratings()
    model    = PoissonDC()

    # Debug: how many team names match ratings?
    missing = set()
    matched = set()
    for fx in fixtures:
        hn, an = norm(fx["home"]), norm(fx["away"])
        if hn in ratings: matched.add(hn)
        else: missing.add(fx["home"])
        if an in ratings: matched.add(an)
        else: missing.add(fx["away"])
    if missing:
        print(f"[warn] missing ratings for {len(missing)} teams: {sorted(list(missing))[:10]}{' ...' if len(missing)>10 else ''}")
    print(f"[info] ratings matched for ~{len(matched)} normalised names")

    predictions = []
    tips = []

    for fx in fixtures:
        h, a = fx["home"], fx["away"]
        hn, an = norm(h), norm(a)
        r_h = float(ratings.get(hn, 0.0))
        r_a = float(ratings.get(an, 0.0))

        M, lam, mu = model.build_grid(r_h, r_a)

        # Early warning if something looks off
        if (lam + mu) < 0.35:
            print(f"[warn] Very small rates for {h} vs {a}: lam={lam:.2f}, mu={mu:.2f} (check ratings or baselines)")

        pH, pD, pA = model.probs_from_grid(M)
        btts_y, btts_n, over25, under25 = model.btts_over_under_from_grid(M)
        ex_h, ex_a = model.expected_goals_from_grid(M)
        top_scores = model.top_scorelines(M, k=3)

        predictions.append({
            "match_id": fx["match_id"],
            "fd_id": fx.get("fd_id", ""),
            "home": h, "away": a,
            "kickoff_utc": fx["kickoff_utc"],
            "probs": {"home": round(pH,4), "draw": round(pD,4), "away": round(pA,4)},
            "btts": {"yes": round(btts_y,4), "no": round(btts_n,4)},
            "totals_2_5": {"over": round(over25,4), "under": round(under25,4)},
            "xg": {"home": round(ex_h,2), "away": round(ex_a,2)},
            "scorelines_top": [
                {"home_goals": s["home_goals"], "away_goals": s["away_goals"], "prob": round(s["prob"],4)}
                for s in top_scores
            ],
            "model_version": "poisson_dc_v1"
        })

        pick, p_pick = most_likely_1x2(predictions[-1]["probs"])
        tips.append({
            "match_id": fx["match_id"],
            "home": h, "away": a,
            "tip": {"market": "1X2", "selection": pick},
            "model_prob": round(p_pick,4),
            "alternatives": []
        })

    generated_ts = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(OUT_DIR, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_utc": generated_ts, "predictions": predictions}, f, indent=2)

    with open(os.path.join(OUT_DIR, "tips.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_utc": generated_ts, "rules": {"tip_policy":"1X2_max"}, "tips": tips}, f, indent=2)

    with open(os.path.join(REP_DIR, "PR_BODY.md"), "w", encoding="utf-8") as f:
        f.write("# Predictions update\n\n")
        f.write(f"Generated: {generated_ts}\n\n")
        f.write("## Picks\n")
        for t in tips:
            f.write(f"- **{t['home']} vs {t['away']}** — 1X2 / {t['tip']['selection']} (model {t['model_prob']:.0%})\n")

if __name__ == "__main__":
    main()
