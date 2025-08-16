# scripts/evaluate_backtest.py
import os, json, csv, math, glob
from datetime import datetime, timezone, timedelta
import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
HIST_DIR = os.path.join(DATA_DIR, "history")
METRICS_DIR = os.path.join(DATA_DIR, "metrics")

ALIASES = {
    "Wolverhampton Wanderers": "Wolves",
    "Wolverhampton": "Wolves",
    "Brighton & Hove Albion": "Brighton",
    "AFC Bournemouth": "Bournemouth",
    "Nott'ham Forest": "Nottingham Forest",
    "Nottingham Forest FC": "Nottingham Forest",
    "Manchester City FC": "Manchester City",
    "Manchester United FC": "Manchester United",
    "Newcastle United FC": "Newcastle United",
    "Tottenham Hotspur FC": "Tottenham Hotspur",
    "Chelsea FC": "Chelsea",
    "Arsenal FC": "Arsenal",
    "Liverpool FC": "Liverpool",
    "Everton FC": "Everton",
    "Aston Villa FC": "Aston Villa",
    "West Ham United FC": "West Ham United",
    "Crystal Palace FC": "Crystal Palace",
    "Brentford FC": "Brentford",
    "Fulham FC": "Fulham",
    "Leeds United FC": "Leeds United",
    "Leicester City FC": "Leicester City",
    "Southampton FC": "Southampton",
    "Burnley FC": "Burnley",
    "Ipswich Town FC": "Ipswich Town",
}
def _norm(n:str)->str:
    if not n: return "Unknown"
    n = n.replace(" FC","").replace(" A.F.C.","").strip()
    return ALIASES.get(n, n)

def read_history():
    files = sorted(glob.glob(os.path.join(HIST_DIR, "preds_*.json")))
    out = []
    for p in files:
        with open(p, "r", encoding="utf-8") as f:
            js = json.load(f)
        ts = js.get("generated_utc") or ""
        # predictions may be at top-level or under key 'predictions'
        preds = js.get("predictions", []) if isinstance(js, dict) else []
        out.append((ts, preds))
    out.sort(key=lambda x: x[0])
    return out

def fetch_finished(days_back=120):
    token = os.getenv("FOOTBALL_DATA_TOKEN","").strip()
    if not token:
        print("[eval] FOOTBALL_DATA_TOKEN missing; cannot fetch results")
        return []
    now = datetime.now(timezone.utc)
    date_to = now.date().isoformat()
    date_from = (now - timedelta(days=days_back)).date().isoformat()
    url = f"https://api.football-data.org/v4/competitions/PL/matches?status=FINISHED&dateFrom={date_from}&dateTo={date_to}"
    r = requests.get(url, headers={"X-Auth-Token":token, "Accept":"application/json"}, timeout=30)
    r.raise_for_status()
    return r.json().get("matches", []) or []

def outcome_from_score(gh, ga):
    return "Home" if gh>ga else "Away" if gh<ga else "Draw"

def main():
    os.makedirs(METRICS_DIR, exist_ok=True)
    batches = read_history()
    if not batches:
        print("[eval] no history snapshots found")
        # Write empty shells so the UI doesn't 404
        with open(os.path.join(METRICS_DIR,"rolling_summary.json"),"w") as f:
            json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(),
                       "last_30_days":{"n":0,"hit_rate":None,"brier":None,"logloss":None},
                       "lifetime":{"n":0,"hit_rate":None,"brier":None,"logloss":None}}, f, indent=2)
        with open(os.path.join(METRICS_DIR,"calibration.json"),"w") as f:
            json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(),
                       "buckets":[{"lo":i,"hi":i+10,"n":0,"avg_pred":0.0,"hit_rate":0.0} for i in range(0,100,10)]}, f, indent=2)
        with open(os.path.join(METRICS_DIR,"match_level.csv"),"w",newline="") as f:
            f.write("batch_ts,kickoff_utc,home,away,gh,ga,p_home,p_draw,p_away,outcome,top_pick,hit,logloss,brier\n")
        return

    # Build indices over archived predictions
    index_by_fd = {}
    index_by_name = []  # (ts, ko, home, away, row)
    for ts, preds in batches:
        for p in preds:
            fd = str(p.get("fd_id") or "")
            if fd:
                index_by_fd.setdefault(fd, []).append((ts, p))
            try:
                ko = datetime.fromisoformat((p.get("kickoff_utc","")).replace("Z","+00:00"))
            except Exception:
                ko = None
            index_by_name.append((ts, ko, _norm(p.get("home","")), _norm(p.get("away","")), p))

    finished = fetch_finished(days_back=120)
    rows = []
    for m in finished:
        gh = ((m.get("score") or {}).get("fullTime") or {}).get("home")
        ga = ((m.get("score") or {}).get("fullTime") or {}).get("away")
        if gh is None or ga is None:
            continue
        fd_id = str(m.get("id") or "")
        ko = datetime.fromisoformat((m.get("utcDate","")).replace("Z","+00:00"))
        hname = _norm((m.get("homeTeam") or {}).get("name","Home"))
        aname = _norm((m.get("awayTeam") or {}).get("name","Away"))
        outcome = outcome_from_score(gh, ga)

        cand = None
        best_ts = None

        # Prefer fd_id match: last snapshot BEFORE KO
        if fd_id in index_by_fd:
            for ts, p in index_by_fd[fd_id]:
                ts_dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
                if ts_dt < ko:
                    if (best_ts is None) or (ts_dt > datetime.fromisoformat(best_ts.replace("Z","+00:00"))):
                        cand = p; best_ts = ts

        # Fallback: name+date match
        if cand is None:
            for ts, p_ko, ph, pa, p in index_by_name:
                if p_ko and ph==hname and pa==aname and p_ko.date()==ko.date():
                    ts_dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
                    if ts_dt < ko:
                        if (best_ts is None) or (ts_dt > datetime.fromisoformat(best_ts.replace("Z","+00:00"))):
                            cand = p; best_ts = ts

        if not cand:
            continue

        pH = float(cand["probs"]["home"]); pD = float(cand["probs"]["draw"]); pA = float(cand["probs"]["away"])
        eps = 1e-12
        p_true = pH if outcome=="Home" else pD if outcome=="Draw" else pA
        logloss = -math.log(max(p_true, eps))
        yH, yD, yA = (1.0 if outcome=="Home" else 0.0), (1.0 if outcome=="Draw" else 0.0), (1.0 if outcome=="Away" else 0.0)
        brier = (pH-yH)**2 + (pD-yD)**2 + (pA-yA)**2
        top_pick = "Home" if pH>=pD and pH>=pA else ("Draw" if pD>=pA else "Away")
        hit = int(top_pick == outcome)

        rows.append({
            "batch_ts": best_ts, "kickoff_utc": ko.isoformat(),
            "home": hname, "away": aname, "gh": gh, "ga": ga,
            "p_home": round(pH,4), "p_draw": round(pD,4), "p_away": round(pA,4),
            "outcome": outcome, "top_pick": top_pick, "hit": hit,
            "logloss": round(logloss,6), "brier": round(brier,6)
        })

    # Write outputs
    os.makedirs(METRICS_DIR, exist_ok=True)
    csv_path = os.path.join(METRICS_DIR, "match_level.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["batch_ts","kickoff_utc","home","away","gh","ga","p_home","p_draw","p_away","outcome","top_pick","hit","logloss","brier"])
        w.writeheader()
        for r in rows: w.writerow(r)

    now = datetime.now(timezone.utc)
    def in_last(days, r):
        try:
            ko = datetime.fromisoformat(r["kickoff_utc"].replace("Z","+00:00"))
        except Exception:
            return False
        return (now - ko).days <= days

    last30 = [r for r in rows if in_last(30, r)]
    def agg(ss):
        if not ss: return {"n":0,"hit_rate":None,"brier":None,"logloss":None}
        n = len(ss)
        hit = sum(r["hit"] for r in ss)/n
        bri = sum(r["brier"] for r in ss)/n
        ll  = sum(r["logloss"] for r in ss)/n
        return {"n":n,"hit_rate":round(hit,3),"brier":round(bri,4),"logloss":round(ll,4)}

    summary = {
        "generated_utc": now.isoformat(),
        "last_30_days": agg(last30),
        "lifetime": agg(rows)
    }
    with open(os.path.join(METRICS_DIR,"rolling_summary.json"),"w",encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Calibration buckets by top-pick probability
    buckets = [{"lo":i, "hi":i+10, "n":0, "avg_pred":0.0, "hit_rate":0.0} for i in range(0,100,10)]
    sums_pred = [0.0]*10; sums_hit = [0]*10; counts = [0]*10
    for r in rows:
        top_p = max(r["p_home"], r["p_draw"], r["p_away"])
        idx = min(9, int(top_p*100)//10)
        counts[idx] += 1
        sums_pred[idx] += top_p
        sums_hit[idx] += r["hit"]
    for i in range(10):
        n = counts[i]
        buckets[i]["n"] = n
        buckets[i]["avg_pred"] = round( (sums_pred[i]/n) if n>0 else 0.0 , 3)
        buckets[i]["hit_rate"] = round( (sums_hit[i]/n) if n>0 else 0.0 , 3)
    with open(os.path.join(METRICS_DIR,"calibration.json"),"w",encoding="utf-8") as f:
        json.dump({"generated_utc": now.isoformat(), "buckets": buckets}, f, indent=2)

    print(f"[eval] wrote {csv_path}, rolling_summary.json, calibration.json")

if __name__ == "__main__":
    main()
