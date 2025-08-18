# scripts/fetch_understat_xg.py
import csv
import json
import re
import time
from dataclasses import dataclass
from typing import List, Dict

import requests

# Understat league slug for the Premier League is "EPL"
LEAGUE_SLUG = "EPL"
DEFAULT_SEASONS = ["2023", "2024", "2025"]  # adjust if you want more/less
OUT_CSV = "data/understat_matches.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

@dataclass
class MatchRow:
    season: str
    date: str
    home: str
    away: str
    home_xg: float
    away_xg: float
    home_goals: int
    away_goals: int
    match_id: str

def _extract_embedded_json(html: str, key: str):
    """
    Understat renders data into <script> as:
      key = JSON.parse('...escaped json...');
    or sometimes: key = [...];
    Return parsed Python data or [] if not found.
    """
    pat = rf"{key}\s*=\s*JSON\.parse\('([^']+)'\)"
    m = re.search(pat, html)
    if m:
        raw = m.group(1).encode("utf-8").decode("unicode_escape")
        return json.loads(raw)

    # fallback: direct array assignment
    pat2 = rf"{key}\s*=\s*(\[[\s\S]*?\]);"
    m2 = re.search(pat2, html)
    if m2:
        return json.loads(m2.group(1))

    return []

def fetch_season(season: str) -> List[MatchRow]:
    url = f"https://understat.com/league/{LEAGUE_SLUG}/{season}"
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    html = r.text

    matches = _extract_embedded_json(html, "matchesData")
    rows: List[MatchRow] = []

    for m in matches:
        try:
            # date is like "2024-08-18 16:30:00"
            date = (m.get("datetime") or m.get("date", ""))[:10]

            # team titles
            home = m.get("h", {}).get("title") or m.get("team_h", "")
            away = m.get("a", {}).get("title") or m.get("team_a", "")

            # nested xG (most common)
            hxg = m.get("xG", {}).get("h")
            axg = m.get("xG", {}).get("a")

            # fallbacks if schema differs
            if hxg is None:
                hxg = m.get("xG_h") or m.get("h_xG")
            if axg is None:
                axg = m.get("xG_a") or m.get("a_xG")

            hxg = float(hxg if hxg is not None else 0.0)
            axg = float(axg if axg is not None else 0.0)

            # goals format varies too
            if "goals" in m and isinstance(m["goals"], dict):
                hg = int(m["goals"].get("h", 0))
                ag = int(m["goals"].get("a", 0))
            else:
                hg = int(m.get("goals_h", 0))
                ag = int(m.get("goals_a", 0))

            match_id = str(m.get("id", ""))

        except Exception:
            # one bad item shouldn't kill the whole season
            continue

        rows.append(
            MatchRow(
                season=season,
                date=date,
                home=home,
                away=away,
                home_xg=hxg,
                away_xg=axg,
                home_goals=hg,
                away_goals=ag,
                match_id=match_id,
            )
        )

    return rows

def main():
    import os
    seasons_env = os.getenv("US_SEASONS", "")
    seasons = [s.strip() for s in seasons_env.split(",") if s.strip()] or DEFAULT_SEASONS

    all_rows: List[MatchRow] = []
    for s in seasons:
        print(f"[understat] fetching {LEAGUE_SLUG} {s} …")
        try:
            rows = fetch_season(s)
            print(f"[understat] {s}: {len(rows)} matches")
            all_rows.extend(rows)
            time.sleep(0.7)  # be nice to the site
        except Exception as e:
            print(f"[understat] failed {s}: {e}")

    print(f"[understat] writing {len(all_rows)} rows -> {OUT_CSV}")
    # ensure the data folder exists
    import pathlib
    pathlib.Path("data").mkdir(parents=True, exist_ok=True)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "season", "date", "home", "away",
            "home_xg", "away_xg", "home_goals", "away_goals", "match_id"
        ])
        for r in all_rows:
            w.writerow([r.season, r.date, r.home, r.away,
                        r.home_xg, r.away_xg, r.home_goals, r.away_goals, r.match_id])

if __name__ == "__main__":
    main()
