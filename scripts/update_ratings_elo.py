# scripts/update_ratings_elo.py
import os, json, csv, math
from datetime import datetime, timedelta, timezone
import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

ALIASES = {
    "Wolverhampton Wanderers": "Wolves",
    "Wolverhampton": "Wolves",
    "Brighton & Hove Albion": "Brighton",
    "AFC Bournemouth": "Bournemouth",
    "Nott'ham Forest": "Nottingham Forest",
    "Manchester City FC": "Manchester City",
    "Man City": "Manchester City",
    "Manchester Utd": "Manchester United",
    "Man United": "Manchester United",
}

def norm(name:str) -> str:
    if not name: return "Unknown"
    n = name.replace(" FC","").replace(" A.F.C.","").strip()
    return ALIASES.get(n, n)

def fetch_finished_matches():
    token = os.getenv("FOOTBALL_DATA_TOKEN","").strip()
    if not token:
        raise RuntimeError("FOOTBALL_DATA_TOKEN missing")
    # last 370 days is enough to cover current season
    now = datetime.now(timezone.utc)
    date_to   = now.date().isoformat()
    date_from = (now - timedelta(days=370)).date().isoformat()
    url = ( "https://api.football-data.org/v4/competitions/PL/matches"
            f"?status=FINISHED&dateFrom={date_from}&dateTo={date_to}" )
    r = requests.get(url, headers={"X-Auth-Token": token, "Accept":"application/json"}, timeout=25)
    r.raise_for_status()
    js = r.json()
    return js.get("matches", [])

def elo_update():
    matches = fetch_finished_matches()
    matches.sort(key=lambda m: m.get("utcDate",""))
    # Elo params
    K = 20.0
    HOME_ADV = 60.0  # elo points
    START = 1500.0

    ratings = {}
    def R(t): return ratings.get(t, START)

    n_games = 0
    for m in matches:
        h = norm(m.get("homeTeam",{}).get("name","Home"))
        a = norm(m.get("awayTeam",{}).get("name","Away"))
        ft = (m.get("score",{}) or {}).get("fullTime",{}) or {}
        gh, ga = ft.get("home"), ft.get("away")
        if gh is None or ga is None:
            continue
        # actual
        if gh > ga: ah = 1.0
        elif gh == ga: ah = 0.5
        else: ah = 0.0
        # expected with home advantage
        rh, ra = R(h), R(a)
        exp_h = 1.0 / (1.0 + 10.0 ** (-( (rh + HOME_ADV) - ra)/400.0))
        delta = K * (ah - exp_h)
        ratings[h] = rh + delta
        ratings[a] = ra - delta
        n_games += 1

    # write CSV used by generate.py (column name 'ExpPts' is fine; loader z-scores it)
    out_csv = os.path.join(DATA_DIR,"team_ratings.csv")
    rows = [{"Team": t, "ExpPts": round(r,1)} for t,r in sorted(ratings.items(), key=lambda x: x[0])]
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Team","ExpPts"])
        w.writeheader(); w.writerows(rows)

    # optional debug
    with open(os.path.join(DATA_DIR,"ratings_elo.json"),"w") as f:
        json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(),
                   "games_used": n_games, "ratings": rows}, f, indent=2)
    print(f"[ratings] Elo updated {len(rows)} teams from {n_games} finished matches → data/team_ratings.csv")

if __name__ == "__main__":
    elo_update()
