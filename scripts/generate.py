# scripts/generate.py
import os
import json
from datetime import datetime, timezone

from scripts.model import PoissonDC
from scripts.sources import load_fixtures, load_team_ratings

# Output directories
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
REP_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")


def most_likely_1x2(probs):
    """Return ('Home'|'Draw'|'Away', prob_float) from a probs dict like {'home':..., 'draw':..., 'away':...}."""
    items = [
        ("Home", probs.get("home", 0.0)),
        ("Draw", probs.get("draw", 0.0)),
        ("Away", probs.get("away", 0.0)),
    ]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[0]


def alt_picks(pred):
    """
    Build a couple of alternative picks with their probabilities.
    Format: list of dicts with keys: market, selection, prob
    """
    alts = []
    alts.append({"market": "BTTS", "selection": "Yes", "prob": pred["btts"]["yes"]})
    alts.append({"market": "BTTS", "selection": "No",  "prob": pred["btts"]["no"]})
    alts.append({"market": "O2.5", "selection": "Over", "prob": pred["totals_2_5"]["over"]})
    alts.append({"market": "O2.5", "selection": "Under","prob": pred["totals_2_5"]["under"]})
    # sort and take top 2 unique by (market, selection)
    alts.sort(key=lambda x: x["prob"], reverse=True)
    out = []
    seen = set()
    for a in alts:
        key = (a["market"], a["selection"])
        if key not in seen:
            out.append(a)
            seen.add(key)
        if len(out) >= 2:
            break
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(REP_DIR, exist_ok=True)

    fixtures = load_fixtures()            # respects FD_WINDOW_DAYS env if set
    ratings  = load_team_ratings()        # may be empty / partial early season

    model = PoissonDC()                   # safe baselines & floor built-in

    predictions = []
    tips = []

    for fx in fixtures:
        h = fx["home"]
        a = fx["away"]
        r_h = float(ratings.get(h, 0.0))
        r_a = float(ratings.get(a, 0.0))

        # Build grid
        M, lam, mu = model.build_grid(r_h, r_a)

        # ---- Small warning if rates look suspiciously small ----
        if (lam + mu) < 0.35:
            print(f"[warn] Very small rates for {h} vs {a}: lam={lam:.2f}, mu={mu:.2f} (check ratings or baselines)")

        # 1X2
        pH, pD, pA = model.probs_from_grid(M)
        # BTTS / Totals
        btts_y, btts_n, over25, under25 = model.btts_over_under_from_grid(M)
        # xG
        ex_h, ex_a = model.expected_goals_from_grid(M)
        # top correct scores
        top_scores = model.top_scorelines(M, k=3)

        pred_row = {
            "match_id": fx["match_id"],
            "fd_id": fx.get("fd_id"),
            "home": h,
            "away": a,
            "kickoff_utc": fx["kickoff_utc"],
            "probs": {
                "home": round(pH, 4),
                "draw": round(pD, 4),
                "away": round(pA, 4),
            },
            "btts": {
                "yes": round(btts_y, 4),
                "no":  round(btts_n, 4),
            },
            "totals_2_5": {
                "over": round(over25, 4),
                "under": round(under25, 4),
            },
            "xg": {
                "home": round(ex_h, 3),
                "away": round(ex_a, 3),
            },
            "scorelines_top": [
                {"home_goals": s["home_goals"], "away_goals": s["away_goals"], "prob": round(s["prob"], 4)}
                for s in top_scores
            ],
            "model_version": "poisson_dc_v1",
        }
        predictions.append(pred_row)

        # Simple "best bet" = most likely 1X2
        pick, p_pick = most_likely_1x2(pred_row["probs"])
        alt = alt_picks(pred_row)
        tips.append({
            "match_id": fx["match_id"],
            "home": h,
            "away": a,
            "tip": {"market": "1X2", "selection": pick},
            "model_prob": round(p_pick, 4),
            "alternatives": [
                {"market": a1["market"], "selection": a1["selection"], "prob": round(a1["prob"], 4)} for a1 in alt
            ]
        })

    # Write predictions JSON
    generated_ts = datetime.now(timezone.utc).isoformat()
    out_pred = {
        "generated_utc": generated_ts,
        "predictions": predictions
    }
    with open(os.path.join(OUT_DIR, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump(out_pred, f, indent=2)

    # Write tips JSON
    out_tips = {
        "generated_utc": generated_ts,
        "rules": {"note": "Simple best 1X2 pick by model probability; alts show highest BTTS/O2.5 edges."},
        "tips": tips
    }
    with open(os.path.join(OUT_DIR, "tips.json"), "w", encoding="utf-8") as f:
        json.dump(out_tips, f, indent=2)

    # Write a succinct PR body
    with open(os.path.join(REP_DIR, "PR_BODY.md"), "w", encoding="utf-8") as f:
        f.write("# Weekly predictions update\n\n")
        f.write(f"Generated: {generated_ts}\n\n")
        f.write("## Picks (probability-first)\n")
        for t, p in zip(tips, predictions):
            h = p["home"]
            a = p["away"]
            rec = f"{t['tip']['market']} / {t['tip']['selection']} (model {t['model_prob']:.0%})"
            # Alternatives
            if t["alternatives"]:
                alts_str = ", ".join([f"{a1['market']} {a1['selection']} {a1['prob']:.0%}" for a1 in t["alternatives"]])
                line = f"- **{h} vs {a}** — {rec} | Alts: {alts_str}\n"
            else:
                line = f"- **{h} vs {a}** — {rec}\n"
            f.write(line)


if __name__ == "__main__":
    main()
