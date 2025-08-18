# scripts/fetch_understat_xg.py
import os
import csv
import asyncio
from datetime import datetime
from typing import List

import aiohttp
from understat import Understat

OUT_PATH = "data/understat_matches.csv"

def _parse_seasons(env_val: str) -> List[int]:
    seasons = []
    if env_val:
        for part in env_val.split(","):
            part = part.strip()
            if part.isdigit():
                seasons.append(int(part))
    return seasons

async def _fetch(seasons: List[int], league: str, sleep_ms: int = 300) -> int:
    """
    Fetch league matches from Understat for the requested seasons and write a CSV.

    Returns number of rows written.
    """
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    # Use a regular browser UA to reduce chance of 403
    headers = {
        "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        understat = Understat(session)

        total_rows = 0
        with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "season", "date", "home", "away",
                "home_goals", "away_goals",
                "home_xg", "away_xg"
            ])

            for season in seasons:
                try:
                    # understat expects lower-case league code like "epl"
                    matches = await understat.get_league_matches(league, season)
                except Exception as e:
                    print(f"[understat] ERROR fetching {league} {season}: {e}")
                    continue

                rows_this_season = 0
                for m in matches:
                    # Only take finished matches (have result)
                    if not (m.get("goals") and m["goals"].get("h") is not None):
                        continue

                    try:
                        date_str = m["datetime"]
                        # understat returns iso string; normalize to date
                        date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()

                        home = m["h"]["title"]
                        away = m["a"]["title"]
                        hg = int(m["goals"]["h"])
                        ag = int(m["goals"]["a"])

                        # Understat xG are in "xG" arrays (list of shots). Sum them if present.
                        hxg = float(m.get("xg", {}).get("h", 0.0)) if isinstance(m.get("xg", {}).get("h", 0.0), (int, float)) else 0.0
                        axg = float(m.get("xg", {}).get("a", 0.0)) if isinstance(m.get("xg", {}).get("a", 0.0), (int, float)) else 0.0

                        writer.writerow([season, date.isoformat(), home, away, hg, ag, round(hxg, 3), round(axg, 3)])
                        rows_this_season += 1
                    except Exception as e:
                        # Skip any odd row rather than failing the whole season
                        print(f"[understat] warn skipping row in {season}: {e}")

                print(f"[understat] season {season}: wrote {rows_this_season} rows")
                total_rows += rows_this_season

                # be polite
                await asyncio.sleep(max(sleep_ms, 0) / 1000)

    print(f"[understat] wrote total {total_rows} rows to {OUT_PATH}")
    return total_rows

def main():
    seasons_env = os.getenv("US_SEASONS", "")
    seasons = _parse_seasons(seasons_env)
    if not seasons:
        # default to last 2 seasons if nothing provided
        y = datetime.utcnow().year
        seasons = [y - 1, y]

    league = os.getenv("US_LEAGUE", "epl").strip().lower()  # <— IMPORTANT
    sleep_ms = int(os.getenv("US_SLEEP_MS", "300"))

    print(f"[understat] league={league} seasons={seasons} sleep_ms={sleep_ms}")
    rows = asyncio.get_event_loop().run_until_complete(_fetch(seasons, league, sleep_ms))
    if rows == 0:
        raise SystemExit("[understat] ERROR: 0 rows written; check league code (use lower-case like 'epl') or network")

if __name__ == "__main__":
    main()
