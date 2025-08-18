from __future__ import annotations
import logging
from typing import Callable
import requests

log = logging.getLogger(__name__)
API = "https://api.football-data.org/v4"
TIMEOUT = 30

HttpGet = Callable[[str, dict, dict], requests.Response]

def _default_get(url: str, params: dict, headers: dict) -> requests.Response:
    return requests.get(url, params=params, headers=headers, timeout=TIMEOUT)

def _headers(token: str | None) -> dict:
    return {"X-Auth-Token": token} if token else {}

def fetch_results(token: str | None, comp: str, seasons: list[int], http_get: HttpGet = _default_get):
    """Return DataFrame with columns: utc_date,season,home,away,home_goals,away_goals."""
    import pandas as pd
    rows = []
    for season in seasons:
        try:
            r = http_get(f"{API}/competitions/{comp}/matches",
                         {"season": season, "status": "FINISHED"},
                         _headers(token))
            r.raise_for_status()
            for m in r.json().get("matches", []):
                ft = (m.get("score", {}) or {}).get("fullTime", {}) or {}
                rows.append({
                    "utc_date": m.get("utcDate"),
                    "season": season,
                    "home": (m.get("homeTeam") or {}).get("name"),
                    "away": (m.get("awayTeam") or {}).get("name"),
                    "home_goals": ft.get("home", 0) or 0,
                    "away_goals": ft.get("away", 0) or 0,
                })
        except Exception as e:
            log.warning("fetch_results season %s failed: %s", season, e)
            continue
    cols = ["utc_date","season","home","away","home_goals","away_goals"]
    return pd.DataFrame(rows, columns=cols)

def fetch_fixtures(token: str | None, comp: str, date_from: str, date_to: str,
                   statuses: str = "SCHEDULED,TIMED", http_get: HttpGet = _default_get) -> list[dict]:
    """Return list of fixtures dicts or [] on error."""
    try:
        r = _default_get(f"{API}/competitions/{comp}/matches",
                         {"dateFrom": date_from, "dateTo": date_to, "status": statuses},
                         _headers(token))
        r.raise_for_status()
        return r.json().get("matches", []) or []
    except Exception as e:
        log.warning("fetch_fixtures failed: %s", e)
        return []
