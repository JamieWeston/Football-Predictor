# scripts/generate.py
import json
import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
from dateutil.parser import isoparse

from scripts.team_names import canonical
from scripts.model import poisson_grid, dixon_coles_adjust, markets_from_grid

PRED_JSON = "data/predictions.json"
TIPS_JSON = "data/tips.json"
STRENGTHS_JSON = "data/team_strengths.json"

COMP = "PL"  # Football-Data competition code
MAX_DAYS = int(os.getenv("FD_WINDOW_DAYS", "14"))
FD_STATUSES = os.getenv("FD_STATUSES", "SCHEDULED,TIMED").split(",")
TOKEN = os.environ["FOOTBALL_DATA_TOKEN"]
HEADERS = {"X-Auth-Token": TOKEN, "User-Agent": "pl-predictor/1.0"}

def _fd_url(date_from, date_to, statuses):
    base = f"https://api.football-data.org/v4/competitions/{COMP}/matches"
    return f"{base}?dateFrom={date_from}&dateTo={date_to}&status={','.join(statuses)}"

def load_fixtures():
    start = datetime.now(timezone.utc).date()
    end = start + timedelta(days=MAX_DAYS)
    url = _fd_url(start.isoformat(), end.isoformat(), FD_STATUSES)
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    m = r.json().get("matches", [])
    rows = []
    for x in m:
        rows.append({
            "fd_id": str(x["id"]),
            "utcDate": x["utcDate"],
            "status": x["status"],
            "home": x["homeTeam"]["name"],
            "away": x["awayTeam"]["name"],
        })
    df = pd.DataFrame(rows)
    # ensure order by kickoff
    if not df.empty:
        df["kickoff_utc"] = pd.to_datetime(df["utcDate"], utc=True)
        df = df.sort_values("kickoff_utc")
    return df

def load_strengths():
    if not os.path.exists(STRENGTHS_JSON):
        raise SystemExit(f"[generate] missing {STRENGTHS_JSON}. Run compute_team_strengths first.")
    with open(STRENGTHS_JSON, "r", encoding="utf-8") as f:
        s = json.load(f)
    return s

def rates_for_match(strengths, h_name, a_name):
    h = canonical(h_name)
    a = canonical(a_name)
    tmap = strengths["teams"]

    if h not in tmap or a not in tmap:
        # fallback: try exact without canonical
        if h_name in tmap and a_name in tmap:
            h = h_name; a = a_name
        else:
            raise KeyError(f"unmapped team(s): '{h_name}' or '{a_name}'")

    alpha = strengths["alpha"]
    HA = strengths["home_adv"]
    atk_h = tmap[h]["atk"]
    def_h = tmap[h]["def"]
    atk_a = tmap[a]["atk"]
    def_a = tmap[a]["def"]

    lam = math.exp(alpha + HA + atk_h - def_a)
    mu  = math.exp(alpha +      0 + atk_a - def_h)
    return lam, mu

def main():
    os.makedirs("data", exist_ok=True)

    fixtures = load_fixtures()
    if fixtures is None or fixtures.empty:
        # Smoke test: write empty but clear reason
        out = {"generated_utc": datetime.now(timezone.utc).isoformat(), "predictions": []}
        with open(PRED_JSON, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("[generate] no fixtures returned from Football-Data in the requested window.")
        return

    strengths = load_strengths()

    preds = []
    tips = []

    for _, r in fixtures.iterrows():
        try:
            lam, mu = rates_for_match(strengths, r["home"], r["away"])
        except KeyError as e:
            print(f"[warn] {e}; skipping")
            continue

        if lam + mu < 0.35:
            print(f"[warn] suspiciously small rates for {r['home']} vs {r['away']}: lam={lam:.2f}, mu={mu:.2f}")

        G = poisson_grid(lam, mu)
        G = dixon_coles_adjust(G, lam, mu, rho=-0.13)
        mkts = markets_from_grid(G)

        preds.append({
            "match_id": f"{r['kickoff_utc'].strftime('%Y-%m-%d_%H%M')}_{canonical(r['home'])[:3].upper()}-{canonical(r['away'])[:3].upper()}",
            "fd_id": r["fd_id"],
            "home": r["home"],
            "away": r["away"],
            "kickoff_utc": r["kickoff_utc"].isoformat(),
            "probs": mkts["probs"],
            "btts": mkts["btts"],
            "totals_2_5": mkts["totals_2_5"],
            "xg": {"home": round(lam, 2), "away": round(mu, 2)},
            "scorelines_top": mkts["scorelines_top"],
            "model_version": "bivar_dc_v2",
        })

        # simple tip: choose highest 1X2; show alts BTTS/OU if >55%
        side = max(mkts["probs"], key=mkts["probs"].get)
        p = mkts["probs"][side]
        alts = []
        if mkts["btts"]["yes"] >= 0.55: alts.append({"market": "BTTS Yes", "prob": mkts["btts"]["yes"]})
        if mkts["btts"]["no"] >= 0.55:  alts.append({"market": "BTTS No", "prob": mkts["btts"]["no"]})
        if mkts["totals_2_5"]["over"] >= 0.55:  alts.append({"market": "O2.5 Over", "prob": mkts["totals_2_5"]["over"]})
        if mkts["totals_2_5"]["under"] >= 0.55: alts.append({"market": "U2.5 Under", "prob": mkts["totals_2_5"]["under"]})

        tips.append({
            "match_id": preds[-1]["match_id"],
            "fd_id": r["fd_id"],
            "home": r["home"],
            "away": r["away"],
            "kickoff_utc": r["kickoff_utc"].isoformat(),
            "pick": {"market": "1X2", "selection": side, "prob": p},
            "alts": [{"market": a["market"], "prob": a["prob"]} for a in alts[:3]],
        })

    pred_out = {"generated_utc": datetime.now(timezone.utc).isoformat(), "predictions": preds}
    with open(PRED_JSON, "w", encoding="utf-8") as f:
        json.dump(pred_out, f, ensure_ascii=False, indent=2)

    tips_out = {"generated_utc": datetime.now(timezone.utc).isoformat(), "tips": tips}
    with open(TIPS_JSON, "w", encoding="utf-8") as f:
        json.dump(tips_out, f, ensure_ascii=False, indent=2)

    print(f"[generate] wrote {len(preds)} predictions -> {PRED_JSON}")
    print(f"[generate] wrote {len(tips)} tips -> {TIPS_JSON}")

if __name__ == "__main__":
    main()
