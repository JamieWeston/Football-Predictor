#!/usr/bin/env python3
"""
Fetch finished Premier League results from football-data.org and write
data/fd_results.csv for downstream strength calculation.

Requires the repo secret FOOTBALL_DATA_TOKEN.
"""

import os
import csv
import time
import datetime as dt
import requests
from pathlib import Path
from typing import List

OUT = Path("data/fd_results.csv")
OUT.parent.mkdir(parents=True, exist_ok=True)

API = "https://api.football-data.org/v4/competitions/PL/matches"
HEADERS = {"X-Auth-Token": os.environ.get("FOOTBALL_DATA_TOKEN", "")}

def fetch_window(date_from: str, date_to: str) -> List[dict]:
    params = {
        "status": "FINISHED",
        "dateFrom": date_from,  # YYYY-MM-DD
        "dateTo": date_to
    }
    r = requests.get(API, headers=HEADERS, params=params, timeout=30)
    if r.status_code == 429:
        # Rate limited – back off and try once
        time.sleep(6)
        r = requests.get(API, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("matches", [])

def main():
    token = HEADERS["X-Auth-Token"]
    if not token:
        print("[fd] FOOTBALL_DATA_TOKEN missing; skipping fallback fetch")
        return

    # Pull last ~2 seasons (730 days) in 60-day windows (safe with FD limits)
    today = dt.date.today()
    start = today - dt.timedelta(days=730)

    all_matches = []
    cursor = start
    step = dt.timedelta(days=60)

    while cursor <= today:
        a = cursor
        b = min(cursor + step, today)
        print(f"[fd] window {a} → {b}")
        try:
            all_matches.extend(fetch_window(a.isoformat(), b.isoformat()))
        except Exception as e:
            print(f"[fd] WARN: window {a} → {b} failed: {e}")
        cursor = b + dt.timedelta(days=1)
        time.sleep(0.3)  # be polite

    # Normalise and write CSV
    rows = []
    for m in all_matches:
        if m.get("status") != "FINISHED":
            continue
        try:
            date = m["utcDate"][:10]
            home = m["homeTeam"]["name"]
            away = m["awayTeam"]["name"]
            hg = m["score"]["fullTime"]["home"]
            ag = m["score"]["fullTime"]["away"]
            if hg is None or ag is None:
                continue
            rows.append((date, home, away, int(hg), int(ag)))
        except Exception:
            continue

    # Deduplicate by (date,home,away)
    rows = list({(r[0], r[1], r[2]): r for r in rows}.values())
    rows.sort(key=lambda r: r[0])

    if not rows:
        print("[fd] No rows parsed; leaving any previous fd_results.csv in place")
        return

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "home", "away", "home_goals", "away_goals"])
        w.writerows(rows)

    print(f"[fd] wrote {OUT} with {len(rows)} rows")

if __name__ == "__main__":
    main()
