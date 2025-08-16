# scripts/strengths_xg.py
import os, json, math
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

def norm(name:str)->str:
    if not name: return "Unknown"
    n = name.replace(" FC","").replace(" A.F.C.","").strip()
    return ALIASES.get(n, n)

def fetch_finished():
    token = os.getenv("FOOTBALL_DATA_TOKEN","").strip()
    if not token: raise RuntimeError("FOOTBALL_DATA_TOKEN missing")
    now = datetime.now(timezone.utc)
    date_to = now.date().isoformat()
    date_from = (now - timedelta(days=370)).date().isoformat()
    url = f"https://api.football-data.org/v4/competitions/PL/matches?status=FINISHED&dateFrom={date_from}&dateTo={date_to}"
    r = requests.get(url, headers={"X-Auth-Token":token, "Accept":"application/json"}, timeout=25)
    r.raise_for_status()
    return r.json().get("matches", [])

def build_strengths(half_life_days=120.0, clamp_ha=0.20):
    matches = fetch_finished()
    now = datetime.now(timezone.utc)
    # Weighted sums
    t_stats = {}  # team: dict
    lg_home_g, lg_away_g, tot_w = 0.0, 0.0, 0.0

    for m in matches:
        utc = m.get("utcDate")
        if not utc: continue
        dt = datetime.fromisoformat(utc.replace("Z","+00:00"))
        days = max(0.0, (now - dt).total_seconds()/86400.0)
        w = 0.5 ** (days / half_life_days)  # exponential decay
        h = norm(m.get("homeTeam",{}).get("name","Home"))
        a = norm(m.get("awayTeam",{}).get("name","Away"))
        ft = (m.get("score",{}) or {}).get("fullTime",{}) or {}
        gh, ga = ft.get("home"), ft.get("away")
        if gh is None or ga is None: continue

        for t in (h,a):
            if t not in t_stats:
                t_stats[t] = {"gf":0.0,"ga":0.0,"g_home":0.0,"g_away":0.0,"mh":0.0,"ma":0.0,"w":0.0}
        t_stats[h]["gf"] += gh*w; t_stats[h]["ga"] += ga*w; t_stats[h]["g_home"] += gh*w; t_stats[h]["mh"] += w; t_stats[h]["w"] += w
        t_stats[a]["gf"] += ga*w; t_stats[a]["ga"] += gh*w; t_stats[a]["g_away"] += ga*w; t_stats[a]["ma"] += w; t_stats[a]["w"] += w

        lg_home_g += gh*w; lg_away_g += ga*w; tot_w += w

    # League means
    lg_home_rate = (lg_home_g / max(tot_w,1e-9))
    lg_away_rate = (lg_away_g / max(tot_w,1e-9))
    lg_mean = (lg_home_rate + lg_away_rate)/2.0

    teams = {}
    for t, s in t_stats.items():
        w = max(1e-9, s["w"])
        gf_rate = s["gf"]/w
        ga_rate = s["ga"]/w
        home_rate = (s["g_home"]/max(s["mh"],1e-9)) if s["mh"]>0 else gf_rate
        away_rate = (s["g_away"]/max(s["ma"],1e-9)) if s["ma"]>0 else gf_rate
        # Log-scale strengths vs league mean; def is "reduces opponent"
        att = math.log(max(1e-6, gf_rate) / max(1e-6, lg_mean))
        defn = -math.log(max(1e-6, ga_rate) / max(1e-6, lg_mean))
        # Team-specific home advantage = difference home vs away scoring, centered
        ha_raw = math.log(max(1e-6, home_rate) / max(1e-6, away_rate))
        ha_center = ha_raw - math.log(max(1e-6, lg_home_rate)/max(1e-6, lg_away_rate))
        ha = max(-clamp_ha, min(clamp_ha, ha_center))
        teams[t] = {"att": round(att,4), "def": round(defn,4), "home_adv": round(ha,4), "games_used": round(w,1)}

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "params":{"half_life_days":half_life_days, "league_home_rate":round(lg_home_rate,3), "league_away_rate":round(lg_away_rate,3)},
        "teams": teams
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR,"team_strengths.json"),"w") as f:
        json.dump(out, f, indent=2)
    print(f"[strengths] built strengths for {len(teams)} teams → data/team_strengths.json")

if __name__ == "__main__":
    build_strengths()
