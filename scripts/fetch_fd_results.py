# scripts/fetch_fd_results.py
"""
Fetch completed Premier League match results from football-data.org and write
data/fd_results.csv.

Env:
- FOOTBALL_DATA_TOKEN : API token (required)
- FD_SEASONS          : comma-separated seasons (e.g. "2023,2024,2025"), default "2024,2025"
- FD_SLEEP_MS         : small delay between seasons (default 300)
"""

from __future__ import annotations
import os
import time
from pathlib import Path
from typing import List, Dict, Any
import requests
import pandas as pd


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v.strip() if v else default


def fetch_season(token: str, season: int) -> pd.DataFrame:
    url = f"https://api.football-data.org/v4/competitions/PL/matches?season={season}"
    headers = {"X-Auth-Token": token, "User-Agent": "pl-predictor/1.0"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    rows: List[Dict[str, Any]] = []
    for m in data.get("matches", []):
        if m.get("status") != "FINISHED":
            continue
        score = m.get("score", {}).get("fullTime", {})
        rows.append(
            {
                "season": season,
                "date": m.get("utcDate"),
                "home": m.get("homeTeam", {}).get("name"),
                "away": m.get("awayTeam", {}).get("name"),
                "goals_h": score.get("home"),
                "goals_a": score.get("away"),
            }
        )
    return pd.DataFrame(rows)


def main():
    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    if not token:
        raise SystemExit("FOOTBALL_DATA_TOKEN is required")

    seasons = [
        int(s.strip())
        for s in _env("FD_SEASONS", "2024,2025").split(",")
        if s.strip()
    ]
    sleep_ms = int(_env("FD_SLEEP_MS", "300"))

    frames = []
    for s in seasons:
        try:
            df = fetch_season(token, s)
            print(f"[fd] season {s}: rows={len(df)} (finished matches)")
            frames.append(df)
        finally:
            time.sleep(sleep_ms / 1000.0)

    if not frames:
        raise SystemExit("[fd] ERROR: collected 0 rows")

    out = pd.concat(frames, ignore_index=True)
    Path("data").mkdir(parents=True, exist_ok=True)
    out_path = Path("data/fd_results.csv")
    out.to_csv(out_path, index=False)
    print(f"[fd] wrote {len(out)} rows -> {out_path}")


if __name__ == "__main__":
    main()
