# scripts/fetch_fd_results.py
from __future__ import annotations
import os
from datetime import date
from pathlib import Path
import requests
import pandas as pd

DATA = (Path(__file__).resolve().parent.parent / "data").absolute()
DATA.mkdir(parents=True, exist_ok=True)
OUT = DATA / "fd_results.csv"

TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "")
SEASONS = [s.strip() for s in os.getenv("FD_SEASONS", "2023,2024,2025").split(",") if s.strip()]

API = "https://api.football-data.org/v4"

def _season_dates(season: int):
    # PL season roughly Aug 1 -> Jun 30
    return f"{season}-08-01", f"{season+1}-06-30"

def _fetch_one_season(season: int) -> pd.DataFrame:
    start, end = _season_dates(season)
    url = f"{API}/competitions/PL/matches?status=FINISHED&dateFrom={start}&dateTo={end}"
    headers = {"X-Auth-Token": TOKEN} if TOKEN else {}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    js = r.json()
    rows = []
    for m in js.get("matches", []):
        h = m["homeTeam"]["name"]
        a = m["awayTeam"]["name"]
        gh = m["score"]["fullTime"]["home"] or 0
        ga = m["score"]["fullTime"]["away"] or 0
        d = m["utcDate"][:10]
        rows.append({"season": season, "date": d, "home_team": h, "away_team": a,
                     "home_goals": gh, "away_goals": ga})
    return pd.DataFrame(rows)

def main():
    if not TOKEN:
        print("[fd] WARNING: FOOTBALL_DATA_TOKEN missing – cannot fetch fallback results")
        return
    frames = []
    for s in SEASONS:
        try:
            frames.append(_fetch_one_season(int(s)))
        except Exception as e:
            print(f"[fd] WARN season {s}: {e}")
    if not frames:
        print("[fd] ERROR: no results downloaded")
        return
    df = pd.concat(frames, ignore_index=True)
    df.sort_values(["season", "date"], inplace=True, ignore_index=True)
    df.to_csv(OUT, index=False)
    print(f"[fd] wrote {OUT} ({len(df)} rows)")

if __name__ == "__main__":
    main()
