# plpred/fd_client.py
from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests


def _http_get(url: str, *, headers: Optional[Dict[str, str]] = None,
              params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    """Small wrapper so tests can inject a fake."""
    r = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


# -------------------------------
# Results (finished matches only)
# -------------------------------
def fetch_results(league: str, season: int, *, http_get: Optional[Callable[..., Dict[str, Any]]] = None
                  ) -> pd.DataFrame:
    """
    Football-Data results for a league/season.

    Parameters
    ----------
    league : e.g. 'PL'
    season : int  e.g. 2024
    http_get : test seam (defaults to requests-based _http_get)
    """
    http_get = http_get or _http_get
    token = os.getenv("FOOTBALL_DATA_TOKEN")
    headers = {"X-Auth-Token": token} if token else {}

    url = f"https://api.football-data.org/v4/competitions/{league}/matches"
    params = {"season": int(season), "status": "FINISHED"}
    data = http_get(url, headers=headers, params=params)

    rows: List[Dict[str, Any]] = []
    for m in data.get("matches", []):
        ft = (m.get("score") or {}).get("fullTime") or {}
        hg, ag = ft.get("home"), ft.get("away")
        if hg is None or ag is None:
            continue
        rows.append({
            "match_id": m.get("id"),
            "utc_date": m.get("utcDate"),
            "home": ((m.get("homeTeam") or {}).get("name")),
            "away": ((m.get("awayTeam") or {}).get("name")),
            "home_goals": int(hg),
            "away_goals": int(ag),
            "league": league,
            "season": int(season),
        })

    return pd.DataFrame(rows)


# -------------------------------
# Fixtures (upcoming matches)
# -------------------------------
def fetch_fixtures(*args, **kwargs) -> pd.DataFrame:
    """
    Backwards-compatible fixtures fetch.

    Supports BOTH call styles:
      1) Legacy: fetch_fixtures(session, league, date_from, date_to, http_get=fake)
      2) New:    fetch_fixtures(days=14, token=..., http_get=fake)

    Returns a DataFrame with: [match_id, utc_date, home, away, competition]
    """
    http_get = kwargs.get("http_get") or _http_get
    token = kwargs.get("token") or os.getenv("FOOTBALL_DATA_TOKEN")
    headers = {"X-Auth-Token": token} if token else {}

    # --- legacy positional signature detection
    if len(args) >= 3 and isinstance(args[1], str):
        # (session, league, date_from, date_to, ...)
        league = args[1]
        date_from = args[2]
        date_to = args[3] if len(args) >= 4 else date_from
        url = f"https://api.football-data.org/v4/competitions/{league}/matches"
        params = {"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to}
        data = http_get(url, headers=headers, params=params)
    else:
        # --- modern: rolling window
        days = int(kwargs.get("days") or kwargs.get("days_ahead") or 14)
        today = _dt.date.today()
        date_from = today.isoformat()
        date_to = (today + _dt.timedelta(days=days)).isoformat()
        url = "https://api.football-data.org/v4/matches"
        params = {"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to}
        data = http_get(url, headers=headers, params=params)

    rows: List[Dict[str, Any]] = []
    for m in data.get("matches", []):
        rows.append({
            "match_id": m.get("id"),
            "utc_date": m.get("utcDate"),
            "home": ((m.get("homeTeam") or {}).get("name")),
            "away": ((m.get("awayTeam") or {}).get("name")),
            "competition": ((m.get("competition") or {}).get("code")),
        })
    return pd.DataFrame(rows)

