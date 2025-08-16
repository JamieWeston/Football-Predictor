# scripts/evaluate_backtest.py
import os, json, csv, math, glob
from datetime import datetime, timezone, timedelta
import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
HIST_DIR = os.path.join(DATA_DIR, "history")
METRICS_DIR = os.path.join(DATA_DIR, "metrics")

def read_history():
    files = sorted(glob.glob(os.path.join(HIST_DIR, "preds_*.json")))
    batches = []
    for p in files:
        with open(p,"r") as f:
            js = json.load(f)
        ts = js.get("generated_utc") or ""
        batches.append((ts, js))
    # sort by timestamp
    batches.sort(key=lambda x: x[0])
    return batches

def fetch_finished(days_back=60):
    token = os.getenv("FOOTBALL_DATA_TOKEN","").strip()
    if not token: 
        print("[eval] FOOTBALL_DATA_TOKEN missing; cannot fetch results"); 
        return []
    now = datetime.now(timezone.utc)
    date_to = now.date().isoformat()
    date_from = (now - timedelta(days=days_back)).date().isoformat()
    url = f"https://api.football-data.org/v4/competitions/PL/matches?status=FINISHED&dateFrom={date_from}&dateTo={date_to}"
    r = requests.get(url, headers={"X-Auth-Token":token, "Accept":"application/json"}, timeout=25)
    r.raise_for_status()
    return r.json().get("matches", [])

def outcome_from_score(gh, ga):
    if gh > ga: return "Home"
    if gh < ga: return "Away"
    return "Draw"

def main():
    os.makedirs(METRICS_DIR, exist_ok=True)
    batches = read_history()
    if not batches:
        print("[eval] no history snapshots to evaluate")
        return

    # Build map: for each match, pick the last snapshot BEFORE kickoff
    finished = fetch_finished(days_back=120)
    rows = []  # per-match metrics
    for m in finished:
        mid_dt = m.get("utcDate") or ""
        if not mid_dt: continue
        ko = datetime.fromisoformat(mid_dt.replace("Z","+00:00"))
        hname = (m.get("homeTeam") or {}).get("name","Home")
        aname = (m.get("awayTeam") or {}).get("name","Away")
        # Our match_id format in fixtures is YYYY-MM-DD_HHMM_TLA-TLA, but we also store names in predictions
        # Match by names + kickoff minute (robust enough for our static site)
        gh = ((m.get("score") or {}).get("fullTime") or {}).get("home")
        ga = ((m.get("score") or {}).get("fullTime") or {}).get("away")
        if gh is None or ga is None: 
            continue
        outcome = outcome_from_score(gh, ga)

        # find last batch before KO containing a prediction for these names (fuzzy by name)
        best = None
        best_ts = None
        for ts, js in batches:
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
            except Exception:
                continue
            if ts_dt >= ko:
                break  # batches sorted ascending; later batches all after KO
            preds = js.get("predictions", [])
            cand = None
            for p in preds:
                if p.get("home")==hname and p.get("away")==aname:
                    cand = p; break
            if cand:
                best = cand; best_ts = ts

        if not best:
            continue

        pH = float(best["probs"]["home"]); pD = float(best["probs"]["draw"]); pA = float(best["probs"]["away"])
        eps = 1e-12
        # log loss on true outcome
        p_true = pH if outcome=="Home" else pD if outcome=="Draw" else pA
        logloss = -math.log(max(p_true, eps))
        # Brier (3-class)
        yH, yD, yA = (1.0 if outcome=="Home" else 0.0), (1.0 if outcome=="Draw" else 0.0), (1.0 if outcome=="Away" else 0.0)
        brier = (pH-yH)**2 + (pD-yD)**2 + (pA-yA)**2
        # top pick hit?
        top_pick = "Home" if pH>=pD and pH>=pA else "Draw" if pD>=pA else "Away"
        hit = (top_pick == outcome)

        rows.append({
            "batch_ts": best_ts, "kickoff_utc": ko.isoformat(),
            "home": hname, "away": aname, "gh": gh, "ga": ga,
            "p_home": round(pH,4), "p_draw": round(pD,4), "p_away": round(pA,4),
            "outcome": outcome, "top_pick": top_pick, "hit": int(hit),
            "logloss": round(logloss,6), "brier": round(brier,6)
        })

    # Write match-level CSV
    csv_path = os.path.join(METRICS_DIR, "match_level.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["batch_ts","kickoff_utc","home","away","gh","ga","p_home","p_draw","p_away","outcome","top_pick","hit","logloss","brier"])
        w.writeheader()
        for r in rows: w.writerow(r)

    # Rolling summaries (last 30 days)
    now = datetime.now(timezone.utc)
    def in_last(days, r):
        try:
            ko = datetime.fromisoformat(r["kickoff_utc"].replace("Z","+00:00"))
        except Exception:
            return False
        return (now - ko).days <= days

    for_window = [r for r in rows if in_last(30, r)]
    def agg(ss):
        if not ss: return {"n":0,"hit_rate":None,"brier":None,"logloss":None}
        n = len(ss)
        hit = sum(r["hit"] for r in ss)/n
        bri = sum(r["brier"] for r in ss)/n
        ll  = sum(r["logloss"] for r in ss)/n
        return {"n":n,"hit_rate":round(hit,3),"brier":round(bri,4),"logloss":round(ll,4)}

    summary = {
        "generated_utc": now.isoformat(),
        "last_30_days": agg(for_window),
        "lifetime": agg(rows)
    }
    with open(os.path.join(METRICS_DIR,"rolling_summary.json"),"w") as f:
        json.dump(summary, f, indent=2)

    # Calibration: bucket by the model's top-pick probability
    buckets = [{"lo":i, "hi":i+10, "n":0, "avg_pred":0.0, "hit_rate":0.0} for i in range(0,100,10)]
    sums_pred = [0.0]*10; sums_hit = [0]*10; counts = [0]*10
    for r in rows:
        pH, pD, pA = r["p_home"], r["p_draw"], r["p_away"]
        top_p = max(pH,pD,pA)
        idx = min(9, int(top_p*100)//10)
        counts[idx] += 1
        sums_pred[idx] += top_p
        sums_hit[idx] += r["hit"]
    for i in range(10):
        n = counts[i]
        buckets[i]["n"] = n
        buckets[i]["avg_pred"] = round( (sums_pred[i]/n) if n>0 else 0.0 , 3)
        buckets[i]["hit_rate"] = round( (sums_hit[i]/n) if n>0 else 0.0 , 3)
    with open(os.path.join(METRICS_DIR,"calibration.json"),"w") as f:
        json.dump({"generated_utc": now.isoformat(), "buckets": buckets}, f, indent=2)

    print(f"[eval] wrote {csv_path}, rolling_summary.json, calibration.json")

if __name__ == "__main__":
    main()
