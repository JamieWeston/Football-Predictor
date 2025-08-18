# plpred/fd_client.py
from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests


def _http_get(url: str, *, headers: Optional[Dict[str, str]] = None,
              params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> requests.Response:
    """Real HTTP GET used in production; tests can inject their own."""
    return requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)


def _coerce_json(obj: Any) -> Dict[str, Any]:
    """Accept dict or Response-like Dummy; always return a dict."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "json"):
        try:
            return obj.json() or {}
        except Exception:
            return {}
    # very defensive fallback
    try:
        return dict(obj)  # may raise
    except Exception:
        return {}


# -------------------------------
# Results (finished matches)
# -------------------------------
def fetch_results(*args, **kwargs) -> pd.DataFrame:
    """
    Back-compat + modern signature:

    Legacy (tests):
        fetch_results(session, league, seasons_list, http_get=fake)
           - seasons_list is list[int], we use all or the first one

    Modern (prod):
        fetch_results(league='PL', season=2024, http_get=None)

    Returns columns: [match_id, utc_date, home, away, home_goals, away_goals, league, season]
    """
    http_get: Callable[..., Any] = kwargs.get("http_get") or _http_get
    token = os.getenv("FOOTBALL_DATA_TOKEN")
    headers = {"X-Auth-Token": token} if token else {}

    # --- detect legacy positional: (session, league, seasons_list, ...)
    seasons: List[int] = []
    if len(args) >= 3 and isinstance(args[1], str):
        league = args[1]
        seasons_arg = args[2]
        if isinstance(seasons_arg, Iterable) and not isinstance(seasons_arg, (str, bytes)):
            seasons = [int(x) for x in seasons_arg]
        else:
            seasons = [int(seasons_arg)]
    else:
        # modern
        league = kwargs.get("league") or args[0]
        season = kwargs.get("season")
        if season is None and len(args) >= 2:
            season = args[1]
        seasons = [int(season)]

    frames: List[pd.DataFrame] = []
    for s in seasons:
        url = f"https://api.football-data.org/v4/competitions/{league}/matches"
        params = {"season": int(s), "status": "FINISHED"}
        try:
            r = http_get(url, headers=headers, params=params)
            # real Response may raise later, Dummy doesn't; normalize:
            if hasattr(r, "raise_for_status"):
                try:
                    r.raise_for_status()
                except Exception:
                    # skip bad season quietly
                    continue
            data = _coerce_json(r)
        except requests.HTTPError:
            continue

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
                "season": int(s),
            })
        if rows:
            frames.append(pd.DataFrame(rows))

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["match_id", "utc_date", "home", "away", "home_goals", "away_goals", "league", "season"]
    )


# -------------------------------
# Fixtures (upcoming matches)
# -------------------------------
def fetch_fixtures(*args, **kwargs) -> pd.DataFrame:
    """
    Back-compat + modern signature:

    Legacy (tests):
        fetch_fixtures(session, league, date_from, date_to, http_get=fake)

    Modern (prod):
        fetch_fixtures(days=14, token=..., http_get=None)

    Returns columns: [match_id, utc_date, home, away, competition]
    """
    http_get: Callable[..., Any] = kwargs.get("http_get") or _http_get
    token = kwargs.get("token") or os.getenv("FOOTBALL_DATA_TOKEN")
    headers = {"X-Auth-Token": token} if token else {}

    try:
        # --- legacy positional signature
        if len(args) >= 3 and isinstance(args[1], str):
            league = args[1]
            date_from = args[2]
            date_to = args[3] if len(args) >= 4 else date_from
            url = f"https://api.football-data.org/v4/competitions/{league}/matches"
            params = {"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to}
            r = http_get(url, headers=headers, params=params)
            if hasattr(r, "raise_for_status"):
                try:
                    r.raise_for_status()
                except Exception:
                    return pd.DataFrame(columns=["match_id", "utc_date", "home", "away", "competition"])
            data = _coerce_json(r)
        else:
            # modern: rolling window
            days = int(kwargs.get("days") or kwargs.get("days_ahead") or 14)
            today = _dt.date.today()
            date_from = today.isoformat()
            date_to = (today + _dt.timedelta(days=days)).isoformat()
            url = "https://api.football-data.org/v4/matches"
            params = {"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to}
            r = http_get(url, headers=headers, params=params)
            if hasattr(r, "raise_for_status"):
                try:
                    r.raise_for_status()
                except Exception:
                    return pd.DataFrame(columns=["match_id", "utc_date", "home", "away", "competition"])
            data = _coerce_json(r)
    except requests.HTTPError:
        return pd.DataFrame(columns=["match_id", "utc_date", "home", "away", "competition"])

    rows: List[Dict[str, Any]] = []
    for m in data.get("matches", []):
        rows.append({
            "match_id": m.get("id"),
            "utc_date": m.get("utcDate"),
            "home": ((m.get("homeTeam") or {}).get("name")),
            "away": ((m.get("awayTeam") or {}).get("name")),
            "competition": ((m.get("competition") or {}).get("code")),
        })
    return pd.DataFrame(rows, columns=["match_id", "utc_date", "home", "away", "competition"])
