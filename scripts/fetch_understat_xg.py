# scripts/fetch_understat_xg.py
import csv
import json
import os
import re
import time
from dataclasses import dataclass
from typing import List

import requests


LEAGUE_SLUG = "EPL"
DEFAULT_SEASONS = ["2023", "2024", "2025"]
OUT_CSV = "data/understat_matches.csv"

# A few extra headers help avoid Cloudflare variants
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://understat.com/",
    "Connection": "keep-alive",
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
    Understat typically renders as:
        key = JSON.parse('...')  OR  key = JSON.parse("...")
    Fallback:
        key = [ ... ];
    Return parsed Python object or [] if not found.
    """
    # 1) JSON.parse with single *or* double quotes
    m = re.search(rf"{key}\s*=\s*JSON\.parse\(\s*([\"'])(.*?)\1\s*\)", html)
    if m:
        raw = m.group(2).encode("utf-8").decode("unicode_escape")
        try:
            return json.loads(raw)
        except Exception:
            pass

    # 2) Direct array assignment
    m2 = re.search(rf"{key}\s*=\s*(\[[\s\S]*?\]);", html)
    if m2:
        try:
            return json.loads(m2.group(1))
        except Exception:
            pass

    return []


def fetch_season(session: requests.Session, season: str) -> List[MatchRow]:
    url = f"https://understat.com/league/{LEAGUE_SLUG}/{season}"
    r = session.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    html = r.text

    matches = _extract_embedded_json(html, "matchesData")
    rows: List[MatchRow] = []

    for m in matches:
        try:
            date = (m.get("datetime") or m.get("date", ""))[:10]
            home = m.get("h", {}).get("title") or m.get("team_h", "")
            away = m.get("a", {}).get("title") or m.get("team_a", "")

            # xG can be nested or flattened; try common shapes
            hxg = m.get("xG", {}).get("h")
            axg = m.get("xG", {}).get("a")
            if hxg is None:
                hxg = m.get("xG_h") or m.get("h_xG")
            if axg is None:
                axg = m.get("xG_a") or m.get("a_xG")
            hxg = float(hxg if hxg is not None else 0.0)
            axg = float(axg if axg is not None else 0.0)

            if "goals" in m and isinstance(m["goals"], dict):
                hg = int(m["goals"].get("h", 0))
                ag = int(m["goals"].get("a", 0))
            else:
                hg = int(m.get("goals_h", 0))
                ag = int(m.get("goals_a", 0))

            match_id = str(m.get("id", ""))

        except Exception:
            # skip any odd row but continue the harvest
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
    seasons_env = os.getenv("US_SEASONS", "")
    seasons = [s.strip() for s in seasons_env.split(",") if s.strip()] or DEFAULT_SEASONS

    session = requests.Session()
    all_rows: List[MatchRow] = []

    for s in seasons:
        print(f"[understat] fetching {LEAGUE_SLUG} {s} …")
        try:
            rows = fetch_season(session, s)
            print(f"[understat] {s}: {len(rows)} matches")
            all_rows.extend(rows)
            time.sleep(0.7)  # gentle delay
        except Exception as e:
            print(f"[understat] failed {s}: {e}")

    # Helpful diagnostics if nothing found
    if len(all_rows) == 0:
        print("[understat] ERROR: scraped 0 matches. "
              "This usually means the page shape changed or a Cloudflare variant was served.")
        print("Try re-running; also ensure US_SEASONS includes at least two seasons "
              "(e.g. 2023,2024) so we exceed the learning threshold.")
        # still write an empty file so downstream fails clearly
    else:
        print(f"[understat] writing {len(all_rows)} rows -> {OUT_CSV}")

    # ensure folder and write file
    import pathlib
    pathlib.Path("data").mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "season",
                "date",
                "home",
                "away",
                "home_xg",
                "away_xg",
                "home_goals",
                "away_goals",
                "match_id",
            ]
        )
        for r in all_rows:
            w.writerow(
                [
                    r.season,
                    r.date,
                    r.home,
                    r.away,
                    r.home_xg,
                    r.away_xg,
                    r.home_goals,
                    r.away_goals,
                    r.match_id,
                ]
            )


if __name__ == "__main__":
    main()
