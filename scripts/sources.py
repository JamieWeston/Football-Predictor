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
except Exception:  # pragma: no cover
    requests = None  # type: ignore

# Optional local fallback path (not required)
LOCAL_FIXTURES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures.json")
TEAM_RATINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "team_ratings.json")


def _fd_headers() -> Dict[str, str]:
    token = os.getenv("FOOTBALL_DATA_TOKEN", "").strip()
    if not token:
        return {}
    return {"X-Auth-Token": token}


def _fd_get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if requests is None:
        raise RuntimeError("The 'requests' package is not available. Add it to requirements.txt")
    headers = _fd_headers()
    if not headers:
        raise RuntimeError("FOOTBALL_DATA_TOKEN not set in environment.")
    resp = requests.get(url, headers=headers, params=params, timeout=25)
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

    Uses football-data.org v4. Accept statuses in FD_STATUSES (default: 'SCHEDULED,TIMED').
    """
    # Window
    if window_days is None:
        try:
            window_days = int(os.getenv("FD_WINDOW_DAYS", "14"))
        except ValueError:
            window_days = 14

    # Which statuses to include
    statuses_env = os.getenv("FD_STATUSES", "SCHEDULED,TIMED")
    allowed_statuses = {s.strip().upper() for s in statuses_env.split(",") if s.strip()}

    today = dt.date.today()
    date_from = today.isoformat()
    date_to = (today + dt.timedelta(days=window_days)).isoformat()

    url = "https://api.football-data.org/v4/competitions/PL/matches"
    # Do NOT pass status here; we'll filter locally to allow multiple values robustly
    params = {"dateFrom": date_from, "dateTo": date_to}

    fixtures: List[Dict[str, Any]] = []

    try:
        data = _fd_get(url, params)
        matches = data.get("matches", [])
        for m in matches:
            status = str(m.get("status", "")).upper()
            if status not in allowed_statuses:
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

        fixtures.sort(key=lambda r: r["kickoff_utc"])

        print(f"[fixtures] window {date_from} → {date_to} | statuses={sorted(allowed_statuses)} | count={len(fixtures)}")
        if len(fixtures) == 0:
            print("[fixtures] No fixtures returned. If matches exist, try setting FD_STATUSES='SCHEDULED,TIMED' or widening FD_WINDOW_DAYS.")
        return fixtures

    except Exception as e:
        # Optional fallback to local file
        if os.path.exists(LOCAL_FIXTURES_PATH):
            try:
                with open(LOCAL_FIXTURES_PATH, "r", encoding="utf-8") as f:
                    local = json.load(f)
                print(f"[fixtures] Using local fallback {LOCAL_FIXTURES_PATH} (count={len(local)}) due to error: {e}")
                return list(local)
            except Exception:
                pass
        raise RuntimeError(f"Failed to load fixtures from football-data.org: {e}") from e


def load_team_strengths() -> Dict[str, float]:
    """
    Load scalar ratings from data/team_ratings.json.

    Returns mapping: { 'Chelsea': 0.123, 'Arsenal': -0.045, ... }
    """
    if not os.path.exists(TEAM_RATINGS_PATH):
        print(f"[strengths] {TEAM_RATINGS_PATH} not found; returning neutral ratings.")
        return {}

    try:
        with open(TEAM_RATINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        ratings = {str(k): float(v) for k, v in data.items()}
        print(f"[strengths] loaded {len(ratings)} team ratings from team_ratings.json")
        return ratings
    except Exception as e:
        print(f"[strengths] failed to parse team_ratings.json: {e}; returning neutral ratings.")
        return {}
