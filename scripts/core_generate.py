from __future__ import annotations
import os, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from plpred import log as logmod
from plpred.fd_client import fetch_fixtures
from plpred.predict import outcome_probs, top_scorelines
from plpred.elo import elo_match_probs

def _load_json(path: str, default: dict) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return default
    return default

def main() -> None:
    logmod.setup()

    token = os.getenv("FOOTBALL_DATA_TOKEN")
    comp = os.getenv("FD_COMP", "PL")
    window_days = int(os.getenv("FD_WINDOW_DAYS", "14"))
    statuses = os.getenv("FD_STATUSES", "SCHEDULED,TIMED")
    blend_elo = float(os.getenv("BLEND_ELO", "0.40"))

    strengths = _load_json("data/team_strengths.json",
                           {"league_avg_gpg": 1.35, "home_adv": 1.10, "draw_scale": 1.0, "teams": {}})
    elo = _load_json("data/elo_ratings.json",
                     {"init":1500.0, "scale":400.0, "k_base":20.0, "home_adv_points":60.0, "draw_nu":1.0, "teams": {}})

    base = float(strengths.get("league_avg_gpg", 1.35))
    home_adv = float(strengths.get("home_adv", 1.10))
    draw_scale = float(strengths.get("draw_scale", 1.0))
    teams = strengths.get("teams", {})

    elo_teams = elo.get("teams", {})
    elo_scale = float(elo.get("scale", 400.0))
    elo_ha = float(elo.get("home_adv_points", 60.0))
    elo_nu = float(elo.get("draw_nu", 1.0))
    elo_init = float(elo.get("init", 1500.0))

    now = datetime.now(timezone.utc)
    dfrom = now.date().isoformat()
    dto   = (now + timedelta(days=window_days)).date().isoformat()
    fixtures = fetch_fixtures(token, comp=comp, date_from=dfrom, date_to=dto, statuses=statuses)

    preds = []
    for m in fixtures:
        h = (m.get("homeTeam") or {}).get("name", "?")
        a = (m.get("awayTeam") or {}).get("name", "?")
        k = m.get("utcDate")

        ht = teams.get(h, {})
        at = teams.get(a, {})
        att_h = ht.get("att_home", ht.get("att", 1.0))
        def_h = ht.get("def_home", ht.get("def", 1.0))
        att_a = at.get("att_away", at.get("att", 1.0))
        def_a = at.get("def_away", at.get("def", 1.0))

        lam = max(0.05, base * att_h * def_a * home_adv)
        mu  = max(0.05, base * att_a * def_h)
        pH_pois, pD_pois, pA_pois = outcome_probs(lam, mu, draw_scale=draw_scale, maxg=8)

        Rh = float(elo_teams.get(h, {}).get("elo", elo_init))
        Ra = float(elo_teams.get(a, {}).get("elo", elo_init))
        pH_elo, pD_elo, pA_elo = elo_match_probs(Rh, Ra, home_adv_points=elo_ha, scale=elo_scale, draw_nu=elo_nu)

        w = min(max(blend_elo, 0.0), 1.0)
        pH = (1.0 - w) * pH_pois + w * pH_elo
        pD = (1.0 - w) * pD_pois + w * pD_elo
        pA = (1.0 - w) * pA_pois + w * pA_elo
        s = pH + pD + pA
        if s <= 0:
            pH, pD, pA = 1/3, 1/3, 1/3
        else:
            pH, pD, pA = pH/s, pD/s, pA/s

        preds.append({
            "match_id": f"{k}_{h[:3]}-{a[:3]}",
            "home": h, "away": a, "kickoff_utc": k,
            "xg": {"home": round(lam,2), "away": round(mu,2)},
            "probs": {"home": round(pH,4), "draw": round(pD,4), "away": round(pA,4)},
            "probs_components": {
                "poisson": {"home": round(pH_pois,4), "draw": round(pD_pois,4), "away": round(pA_pois,4)},
                "elo":     {"home": round(pH_elo,4),  "draw": round(pD_elo,4),  "away": round(pA_elo,4)}
            },
            "scorelines_top": top_scorelines(lam, mu, k=3, cap=6),
            "notes": {"blend_elo": w}
        })

    out = {"generated_utc": datetime.now(timezone.utc).isoformat(), "predictions": preds}
    Path("data/predictions.json").write_text(json.dumps(out, indent=2))
    print("[core_generate] wrote data/predictions.json count:", len(preds))

if __name__ == "__main__":
    main()
