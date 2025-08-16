# scripts/fetch_understat_xg.py
import os
import json
import asyncio
import datetime as dt
from typing import List, Dict, Any

import aiohttp
from understat import Understat


LEAGUE = "epl"  # Understat code for the Premier League
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "understat_team_matches.json")


def _season_years() -> List[int]:
    """
    Seasons to fetch. Accepts env var US_SEASONS="2022,2023,2024".
    Defaults to last 3 seasons based on 'August season rollover'.
    """
    env = os.getenv("US_SEASONS")
    if env:
        nums = []
        for tok in env.split(","):
            tok = tok.strip()
            if tok.isdigit():
                nums.append(int(tok))
        if nums:
            return nums

    today = dt.datetime.utcnow()
    base = today.year if today.month >= 8 else today.year - 1
    return [base - 2, base - 1, base]


async def _fetch_one_team(us: Understat, team_name: str, season: int) -> List[Dict[str, Any]]:
    """
    Use Understat.get_team_results(team_name, season)
    Returns match rows with xG / xGA / h_a ('h' or 'a'), opponent, date, scored, conceded.
    """
    try:
        res = await us.get_team_results(team_name, season)
    except Exception as e:
        print(f"[warn] get_team_results({team_name}, {season}) failed: {e}")
        return []

    rows = []
    for r in res:
        # Be defensive about keys / types
        date = r.get("date") or r.get("datetime") or ""
        date = date.split(" ")[0] if date else ""
        h_a = (r.get("h_a") or "").lower()  # 'h' or 'a'
        is_home = h_a == "h"

        def _f(x):
            try:
                return float(x)
            except Exception:
                return None

        def _i(x):
            try:
                return int(x)
            except Exception:
                return None

        rows.append({
            "season": season,
            "date": date,
            "team": r.get("team") or team_name,
            "opponent": r.get("opponent") or r.get("opponent_title") or "",
            "is_home": is_home,
            "xg_for": _f(r.get("xG")),
            "xg_against": _f(r.get("xGA")),
            "goals_for": _i(r.get("scored")),
            "goals_against": _i(r.get("conceded")),
        })
    return rows


async def _fetch(seasons: List[int]) -> List[Dict[str, Any]]:
    """
    Loop seasons; for each season, fetch EPL teams and then per-team results.
    """
    out: List[Dict[str, Any]] = []

    # Optional gentle throttle between API calls
    sleep_ms = int(os.getenv("US_SLEEP_MS", "0"))

    async with aiohttp.ClientSession() as session:
        us = Understat(session)

        for s in seasons:
            # get_teams requires league + season
            teams = await us.get_teams(LEAGUE, s)
            team_names = sorted({t.get("title") for t in teams if t.get("title")})
            print(f"[understat] {len(team_names)} teams for season {s}")

            for name in team_names:
                rows = await _fetch_one_team(us, name, s)
                out.extend(rows)
                if sleep_ms > 0:
                    await asyncio.sleep(sleep_ms / 1000.0)

    return out


def main():
    seasons = _season_years()
    print(f"[understat] seasons: {seasons}")
    rows = asyncio.run(_fetch(seasons))

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"seasons": seasons, "rows": rows}, f, ensure_ascii=False, indent=2)
    print(f"[understat] wrote {len(rows)} rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
