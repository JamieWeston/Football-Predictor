"""
Generate predictions and probability-first tips (with scorelines/cards/corners).

Outputs:
  data/predictions.json
  data/tips.json
  reports/PR_BODY.md
"""

import os, json, math
from datetime import datetime, timezone

# Robust imports for module/script execution
try:
    from .model import PoissonDC
    from .sources import load_fixtures, fetch_best_odds, load_team_ratings
except ImportError:
    from scripts.model import PoissonDC
    from scripts.sources import load_fixtures, fetch_best_odds, load_team_ratings

THIS_DIR = os.path.dirname(__file__)
OUT_DIR  = os.path.abspath(os.path.join(THIS_DIR, "..", "data"))
REP_DIR  = os.path.abspath(os.path.join(THIS_DIR, "..", "reports"))

ALT_THRESHOLD = 0.55     # when to show BTTS/O2.5 as "alternative" picks
MAX_GOALS     = 6
RHO           = -0.05    # DC correlation

def load_strengths():
    path = os.path.join(OUT_DIR, "team_strengths.json")
    if os.path.exists(path):
        with open(path,"r") as f: 
            js = json.load(f)
        return js
    return None

def base_rates_from_strengths(str_js):
    # Use league home/away means from strengths builder
    if not str_js: 
        # sensible defaults if missing
        return 1.55, 1.25
    p = str_js.get("params",{})
    return float(p.get("league_home_rate",1.55)), float(p.get("league_away_rate",1.25))

def lambdas_for_match(home, away, strengths, league_home, league_away):
    # log-link: lam_h = league_home * exp(att_h - def_a + ha_h); mu_a = league_away * exp(att_a - def_h)
    tmap = strengths.get("teams",{}) if strengths else {}
    th = tmap.get(home, {"att":0.0,"def":0.0,"home_adv":0.0})
    ta = tmap.get(away, {"att":0.0,"def":0.0,"home_adv":0.0})
    lam_h = league_home * math.exp(th.get("att",0.0) - ta.get("def",0.0) + th.get("home_adv",0.0))
    mu_a  = league_away * math.exp(ta.get("att",0.0) - th.get("def",0.0))
    return max(0.05, lam_h), max(0.05, mu_a)

# --- Simple props: cards & corners (fast, explainable proxies) ---
def poisson_cdf(k, mean):
    # P(X <= k) for Poisson(mean)
    k = int(k)
    s = 0.0
    for i in range(0, k+1):
        s += math.exp(-mean) * (mean ** i) / math.factorial(i)
    return s

def cards_projection(lam_h, mu_a):
    # Base total ≈ 4.6, away slightly more on average; skew by underdog pressure.
    # Use goal expectation difference as a pressure proxy.
    diff = lam_h - mu_a
    home_mean = 1.9 - 0.15*diff
    away_mean = 2.1 + 0.15*diff
    home_mean = max(1.2, min(3.2, home_mean))
    away_mean = max(1.2, min(3.2, away_mean))
    total = home_mean + away_mean
    over45 = 1 - poisson_cdf(4, total)
    over55 = 1 - poisson_cdf(5, total)
    return {
        "home_mean": round(home_mean,2), "away_mean": round(away_mean,2),
        "over_4_5": round(over45,4), "over_5_5": round(over55,4)
    }

def corners_projection(lam_h, mu_a):
    # Base total ≈ 9.8; teams with higher attacking xG should see more corners.
    # Map expected goals into corners linearly and clamp.
    home = 4.6 + 1.0*(lam_h - 1.4)
    away = 4.2 + 1.0*(mu_a  - 1.1)
    home = max(2.5, min(8.0, home))
    away = max(2.5, min(8.0, away))
    total = home + away
    over95 = 1 - poisson_cdf(9, total)
    over105 = 1 - poisson_cdf(10, total)
    return {
        "home_mean": round(home,2), "away_mean": round(away,2),
        "over_9_5": round(over95,4), "over_10_5": round(over105,4)
    }

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(REP_DIR, exist_ok=True)

    fixtures = load_fixtures()
    strengths = load_strengths()
    league_home, league_away = base_rates_from_strengths(strengths)
    model = PoissonDC(rho=RHO, max_goals=MAX_GOALS)

    # fallback ratings file if strengths missing (kept for safety)
    ratings = load_team_ratings()

    predictions = []
    for fx in fixtures:
        home, away = fx["home"], fx["away"]

        if strengths:
            lam, mu = lambdas_for_match(home, away, strengths, league_home, league_away)
        else:
            # graceful fallback using simple z-scores -> translate to lam/mu around league means
            rh = ratings.get(home, 0.0); ra = ratings.get(away, 0.0)
            lam = league_home * math.exp( 0.25*rh - 0.25*ra )
            mu  = league_away * math.exp( 0.25*ra - 0.25*rh )

        M, lam, mu = model.build_grid(lam, mu)
        pH, pD, pA = model.probs_from_grid(M)
        btts_y, btts_n, over25, under25 = model.btts_over_under_from_grid(M)
        ex_h, ex_a = model.expected_goals_from_grid(M)
        top3 = model.top_k_scores(M, k=3)
        cards = cards_projection(lam, mu)
        corners = corners_projection(lam, mu)

        predictions.append({
            "match_id": fx["match_id"],
            "home": home,
            "away": away,
            "kickoff_utc": fx["kickoff_utc"],
            "probs": {"home": round(pH,4), "draw": round(pD,4), "away": round(pA,4)},
            "btts": {"yes": round(btts_y,4), "no": round(btts_n,4)},
            "totals_2_5": {"over": round(over25,4), "under": round(under25,4)},
            "xg": {"home": round(ex_h,3), "away": round(ex_a,3)},
            "most_likely_scores": [{"score": s, "prob": round(p,4)} for (s,p) in top3],
            "cards": cards,
            "corners": corners,
            "model_version": "poisson_dc_v2"
        })

    # Tips: probability-first (always show a 1X2 pick)
    tips = []
    for p in predictions:
        picks = [("Home", p["probs"]["home"]), ("Draw", p["probs"]["draw"]), ("Away", p["probs"]["away"])]
        sel, prob = max(picks, key=lambda x: x[1])

        alts = []
        if max(p["btts"]["yes"], p["btts"]["no"]) >= ALT_THRESHOLD:
            alts.append({"market":"BTTS","selection":"Yes" if p["btts"]["yes"]>=p["btts"]["no"] else "No","prob": round(max(p["btts"]["yes"], p["btts"]["no"]),4)})
        if max(p["totals_2_5"]["over"], p["totals_2_5"]["under"]) >= ALT_THRESHOLD:
            alts.append({"market":"O2.5","selection":"Over" if p["totals_2_5"]["over"]>=p["totals_2_5"]["under"] else "Under","prob": round(max(p["totals_2_5"]["over"], p["totals_2_5"]["under"]),4)})

        tips.append({
            "match_id": p["match_id"],
            "home": p["home"], "away": p["away"],
            "tip": {"market":"1X2","selection":sel},
            "model_prob": round(prob,4),
            "source": "most-likely",
            "edge_pct": 0.0,
            "alts": alts,
            "top_scores": p["most_likely_scores"],  # handy in UI
            "cards": p["cards"],
            "corners": p["corners"]
        })

    gen = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(OUT_DIR,"predictions.json"),"w") as f:
        json.dump({"generated_utc":gen,"predictions":predictions}, f, indent=2)

    with open(os.path.join(OUT_DIR,"tips.json"),"w") as f:
        json.dump({"generated_utc":gen,"rules":{"mode":"probability-first","alt_threshold":ALT_THRESHOLD},"tips":tips}, f, indent=2)

    # PR body
    os.makedirs(REP_DIR, exist_ok=True)
    with open(os.path.join(REP_DIR,"PR_BODY.md"),"w") as f:
        f.write("# Weekly predictions update\n\n")
        f.write(f"Generated: {gen}\n\n")
        f.write("## Picks (probability-first)\n")
        for t in tips:
            line = f"- **{t['home']} vs {t['away']}** — 1X2 / {t['tip']['selection']} (model {t['model_prob']:.0%})"
            if t["alts"]:
                line += " | Alts: " + ", ".join([f\"{a['market']} {a['selection']} {a['prob']:.0%}\" for a in t['alts']])
            if t.get("top_scores"):
                ts = ", ".join([f\"{s['score']} {s['prob']:.0%}\" for s in t["top_scores"]])
                line += f" | Scores: {ts}"
            f.write(line + "\n")

if __name__ == "__main__":
    main()
