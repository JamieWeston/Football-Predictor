# scripts/fetch_understat_xg.py
"""
Fetch Understat league matches (with xG/goals) for one or more seasons and
write them to data/understat_matches.csv.

Env vars:
- US_LEAGUE   : short league code (e.g., 'epl'). Case-insensitive.
- US_SEASONS  : comma-separated seasons, e.g. '2023,2024,2025'
- US_SLEEP_MS : optional polite delay between seasons (default 300ms)
"""

from __future__ import annotations
import os
import re
import json
import time
from pathlib import Path
from typing import Iterable, List, Dict, Any
import requests
import pandas as pd


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v.strip() if v else default


def _parse_matches_from_html(html: str) -> List[Dict[str, Any]]:
    """
    Understat embeds JSON into a JS variable:
      var matchesData = JSON.parse('...escaped...');
    or sometimes:
      var matchesData = [...];

    This extracts and returns a list of dicts for matches.
    """
    # Pattern 1: JSON.parse('...') form
    m = re.search(r"var\s+matchesData\s*=\s*JSON\.parse\('([^']+)'\)", html)
    if m:
        raw = m.group(1)
        # Understat escapes quotes; decode twice: JS-string -> JSON
        unescaped = bytes(raw, "utf-8").decode("unicode_escape")
        return json.loads(unescaped)

    # Pattern 2: direct JSON array
    m = re.search(r"var\s+matchesData\s*=\s*(\[[\s\S]*?\]);", html)
    if m:
        return json.loads(m.group(1))

    raise RuntimeError("Could not locate matchesData in page")


def fetch_league_season(league_code: str, season: int) -> pd.DataFrame:
    league_path = league_code.upper()  # Understat expects 'EPL', 'La_liga', etc.
    url = f"https://understat.com/league/{league_path}/{season}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    matches = _parse_matches_from_html(resp.text)
    rows = []
    for m in matches:
        # Typical structure:
        # {
        #   "id":"XXXXX",
        #   "datetime":"2024-08-17 14:00:00",
        #   "isResult":true,
        #   "h":{"id":"89","title":"Manchester United","short_title":"Man United"},
        #   "a":{"id":"80","title":"Aston Villa","short_title":"Aston Villa"},
        #   "goals":{"h":2,"a":1},
        #   "xG":{"h":1.54,"a":1.12},
        #   ...
        # }
        # Not all games have results/xG yet (future fixtures). Keep rows that have xG.
        try:
            home = m["h"]["title"]
            away = m["a"]["title"]
            # xG may be strings; coerce to float
            xg_h = float(m["xG"]["h"]) if m.get("xG") else None
            xg_a = float(m["xG"]["a"]) if m.get("xG") else None
            g_h = int(m["goals"]["h"]) if m.get("goals") else None
            g_a = int(m["goals"]["a"]) if m.get("goals") else None
            dt = m.get("datetime")

            # Only keep rows where xG is present (played matches)
            if xg_h is not None and xg_a is not None:
                rows.append(
                    {
                        "season": season,
                        "date": dt,
                        "home": home,
                        "away": away,
                        "goals_h": g_h,
                        "goals_a": g_a,
                        "xg_h": xg_h,
                        "xg_a": xg_a,
                    }
                )
        except Exception:
            # be permissive; skip malformed rows rather than failing the run
            continue

    return pd.DataFrame(rows)


def main():
    league = _env("US_LEAGUE", "epl")          # case-insensitive
    seasons_s = _env("US_SEASONS", "2024,2025")
    sleep_ms = int(_env("US_SLEEP_MS", "300"))

    seasons: Iterable[int] = [int(s.strip()) for s in seasons_s.split(",") if s.strip()]

    all_frames: List[pd.DataFrame] = []
    for s in seasons:
        try:
            df = fetch_league_season(league, s)
            print(f"[understat] season {s}: rows={len(df)}")
            all_frames.append(df)
        except Exception as e:
            print(f"[understat] WARN: failed to parse season {s}: {e}")
        time.sleep(sleep_ms / 1000.0)

    if not all_frames:
        raise SystemExit("[understat] ERROR: collected 0 rows across all seasons")

    out = pd.concat(all_frames, ignore_index=True)
    out_dir = Path("data")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "understat_matches.csv"
    out.to_csv(out_path, index=False)
    print(f"[understat] wrote total {len(out)} rows to {out_path}")


if __name__ == "__main__":
    main()
