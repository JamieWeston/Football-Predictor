"""
Generate predictions and probability-first tips (no odds required).

- Primary tip = most likely 1X2 outcome (Home/Draw/Away)
- Alternatives (optional) = BTTS or Over/Under 2.5 if very likely

Outputs:
  data/predictions.json
  data/tips.json
  reports/PR_BODY.md
"""

import os, json
from datetime import datetime, timezone

# Robust imports (works as module or script)
try:
    from .model import PoissonDC
    from .sources import load_fixtures, load_team_ratings, fetch_best_odds  # fetch_best_odds unused
except ImportError:
    from scripts.model import PoissonDC
    from scripts.sources import load_fixtures, load_team_ratings, fetch_best_odds  # fetch_best_odds unused

THIS_DIR = os.path.dirname(__file__)
OUT_DIR  = os.path.abspath(os.path.join(THIS_DIR, "..", "data"))
REP_DIR  = os.path.abspath(os.path.join(THIS_DIR, "..", "reports"))

# ---- Tunables ----
ALT_THRESHOLD = 0.55   # show BTTS / O2.5 alternatives only if ≥ 55%
# -------------------

def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(REP_DIR, exist_ok=True)

    fixtures = load_fixtures()
    ratings  = load_team_ratings()
    model    = PoissonDC()

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

    # ----- Probability-first tips (no odds) -----
    tips = []
    for p in predictions:
        # Primary = most likely 1X2
        oneX2 = [("Home", p["probs"]["home"]), ("Draw", p["probs"]["draw"]), ("Away", p["probs"]["away"])]
        primary_sel, primary_prob = max(oneX2, key=lambda x: x[1])

        # Alternatives if strong
        alts = []
        if max(p["btts"]["yes"], p["btts"]["no"]) >= ALT_THRESHOLD:
            alts.append({
                "market": "BTTS",
                "selection": "Yes" if p["btts"]["yes"] >= p["btts"]["no"] else "No",
                "prob": round(max(p["btts"]["yes"], p["btts"]["no"]), 4)
            })
        if max(p["totals_2_5"]["over"], p["totals_2_5"]["under"]) >= ALT_THRESHOLD:
            alts.append({
                "market": "O2.5",
                "selection": "Over" if p["totals_2_5"]["over"] >= p["totals_2_5"]["under"] else "Under",
                "prob": round(max(p["totals_2_5"]["over"], p["totals_2_5"]["under"]), 4)
            })

        tips.append({
            "match_id": p["match_id"],
            "home": p["home"],
            "away": p["away"],
            "tip": {"market": "1X2", "selection": primary_sel},
            "model_prob": round(primary_prob, 4),  # 0..1
            "book_odds": None,
            "source": "most-likely",
            "edge_pct": 0.0,
            "alts": alts  # optional array of {market, selection, prob}
        })

    # ----- Write outputs -----
    generated = datetime.now(timezone.utc).isoformat()

    with open(os.path.join(OUT_DIR, "predictions.json"), "w") as f:
        json.dump({"generated_utc": generated, "predictions": predictions}, f, indent=2)

    with open(os.path.join(OUT_DIR, "tips.json"), "w") as f:
        json.dump({
            "generated_utc": generated,
            "rules": {"mode": "probability-first", "alt_threshold": ALT_THRESHOLD},
            "tips": tips
        }, f, indent=2)

    # PR body
    with open(os.path.join(REP_DIR, "PR_BODY.md"), "w") as f:
        f.write("# Weekly predictions update\n\n")
        f.write(f"Generated: {generated}\n\n")
        f.write("## Picks (probability-first)\n")
        for t in tips:
            line = f"- **{t['home']} vs {t['away']}** — 1X2 / {t['tip']['selection']} (model {t['model_prob']:.0%})"
            if t["alts"]:
                altbits = [f"{a['market']} {a['selection']} {a['prob']:.0%}" for a in t["alts"]]
                line += " | Alts: " + ", ".join(altbits)
            f.write(line + "\n")

if __name__ == "__main__":
    main()
