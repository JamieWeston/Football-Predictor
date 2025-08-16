# scripts/sources.py
"""
Shared data-loading helpers used by generate.py

Exports:
- load_fixtures(window_days: int | None) -> list[dict]
- load_team_strengths() -> dict[str, float]
"""

from __future__ import annotations

import os
import json
import datetime as dt
from typing import Any, Dict, List

try:
    import requests
except Exception:  # pragma: no cover (actions will have requests installed)
    requests = None  # type: ignore

# Local optional fallback (not required). If present, should mimic output of load_fixtures().
LOCAL_FIXTURES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures.json")
TEAM_RATINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "team_ratings.json")


# --------------------------------------------------------------------------- #
# Fixtures (football-data.org)
# --------------------------------------------------------------------------- #

def _fd_headers() -> Dict[str, str]:
    token = os.getenv("FOOTBALL_DATA_TOKEN", "").strip()
    if not token:
        return {}
    return {"X-Auth-Token": token}


def _fd_get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if requests is None:
        raise RuntimeError("The 'requests' package is not available.")

    headers = _fd_headers()
    if not headers:
        raise RuntimeError("FOOTBALL_DATA_TOKEN not set in environment.")

    resp = requests.get(url, headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def load_fixtures(window_days: int | None = None) -> List[Dict[str, Any]]:
    """
    Return upcoming PL fixtures as a list of dicts:
      {
        'fd_id': str,
        'home': 'Chelsea',
        'away': 'Arsenal',
        'kickoff_utc': '2025-08-17T13:00:00Z'
      }

    If FOOTBALL_DATA_TOKEN is not available, will try a local fallback file
    at data/fixtures.json (optional).
    """
    if window_days is None:
        try:
            window_days = int(os.getenv("FD_WINDOW_DAYS", "14"))
        except ValueError:
            window_days = 14

    today = dt.date.today()
    date_from = today.isoformat()
    date_to = (today + dt.timedelta(days=window_days)).isoformat()

    # football-data.org v4 endpoint for PL matches by date window
    url = "https://api.football-data.org/v4/competitions/PL/matches"
    params = {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED"}

    fixtures: List[Dict[str, Any]] = []

    try:
        data = _fd_get(url, params)
        matches = data.get("matches", [])
        for m in matches:
            # Only accept Premier League matches that are scheduled
            if m.get("status") != "SCHEDULED":
                continue

            home = (m.get("homeTeam") or {}).get("name")
            away = (m.get("awayTeam") or {}).get("name")
            utc = m.get("utcDate")  # e.g. '2025-08-17T13:00:00Z'
            mid = m.get("id")

            if not all([home, away, utc, mid]):
                continue

            fixtures.append(
                {
                    "fd_id": str(mid),
                    "home": str(home),
                    "away": str(away),
                    "kickoff_utc": str(utc),
                }
            )

        # Sort by kickoff
        fixtures.sort(key=lambda r: r["kickoff_utc"])
        return fixtures

    except Exception as e:
        # Fallback to local fixtures file if it exists
        if os.path.exists(LOCAL_FIXTURES_PATH):
            try:
                with open(LOCAL_FIXTURES_PATH, "r", encoding="utf-8") as f:
                    local = json.load(f)
                # Expecting the same shape as we return above
                return list(local)
            except Exception:
                pass
        # Re-raise with context so the caller can see the cause
        raise RuntimeError(f"Failed to load fixtures from football-data.org: {e}") from e


# --------------------------------------------------------------------------- #
# Team ratings (produced by compute_team_strengths.py)
# --------------------------------------------------------------------------- #

def load_team_strengths() -> Dict[str, float]:
    """
    Load scalar ratings from data/team_ratings.json.

    Returns mapping: { 'Chelsea': 0.123, 'Arsenal': -0.045, ... }
    If the file doesn't exist (first run), returns {} so the caller can
    fall back to neutral ratings (0.0).
    """
    if not os.path.exists(TEAM_RATINGS_PATH):
        return {}

    try:
        with open(TEAM_RATINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Expecting a simple mapping str->float
        return {str(k): float(v) for k, v in data.items()}
    except Exception:
        # Be safe: return empty so generate.py can handle neutral ratings
        return {}
