# plpred/fd_client.py
from __future__ import annotations
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

import requests
import pandas as pd

FD_BASE = "https://api.football-data.org/v4"
PL_CODE = "PL"  # Premier League

def _headers(token: str) -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if token:
        h["X-Auth-Token"] = token
    return h

def _iso_d(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")

def _get(url: str, token: str, params: Dict[str, Any]) -> Dict[str, Any] | None:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=_headers(token), params=params, timeout=20)
            if r.status_code == 429 and attempt < 2:
                retry_after = int(r.headers.get("Retry-After", "2"))
                time.sleep(retry_after)
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 2:
                return None
            time.sleep(1 + attempt)
    return None

def _matches_to_df(matches: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for m in matches:
        try:
            utc_date = m.get("utcDate") or m.get("utc_date")
            home = m["homeTeam"]["name"]
            away = m["awayTeam"]["name"]
            status = (m.get("status") or "").upper()
            score = m.get("score") or {}
            full = score.get("fullTime") or {}
            hg = full.get("home")
            ag = full.get("away")
            rows.append(
                {
                    "utc_date": utc_date,
                    "home": home,
                    "away": away,
                    "status": status,
                    "home_goals": hg if isinstance(hg, int) else None,
                    "away_goals": ag if isinstance(ag, int) else None,
                }
            )
        except Exception:
            continue
    return pd.DataFrame(rows, columns=["utc_date", "home", "away", "status", "home_goals", "away_goals"])

def fetch_fixtures(days: int, token: str = "") -> pd.DataFrame:
    """Upcoming PL fixtures (SCHEDULED) for the next `days` days."""
    if days <= 0:
        return pd.DataFrame(columns=["utc_date", "home", "away"])
    now = datetime.now(timezone.utc)
    date_from = _iso_d(now)
    date_to = _iso_d(now + timedelta(days=days))
    url = f"{FD_BASE}/competitions/{PL_CODE}/matches"
    params = {"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to}
    data = _get(url, token, params)
    if not data or "matches" not in data:
        return pd.DataFrame(columns=["utc_date", "home", "away"])
    df = _matches_to_df(data["matches"])
    if df.empty:
        return pd.DataFrame(columns=["utc_date", "home", "away"])
    return df.loc[:, ["utc_date", "home", "away"]].sort_values("utc_date").reset_index(drop=True)

def fetch_results(days_back: int, token: str = "") -> pd.DataFrame:
    """Finished PL matches in the last `days_back` days."""
    if days_back <= 0:
        return pd.DataFrame(columns=["utc_date", "home", "away", "home_goals", "away_goals"])
    now = datetime.now(timezone.utc)
    date_from = _iso_d(now - timedelta(days=days_back))
    date_to = _iso_d(now)
    url = f"{FD_BASE}/competitions/{PL_CODE}/matches"
    params = {"status": "FINISHED", "dateFrom": date_from, "dateTo": date_to}
    data = _get(url, token, params)
    if not data or "matches" not in data:
        return pd.DataFrame(columns=["utc_date", "home", "away", "home_goals", "away_goals"])
    df = _matches_to_df(data["matches"])
    if df.empty:
        return pd.DataFrame(columns=["utc_date", "home", "away", "home_goals", "away_goals"])
    df = df.loc[:, ["utc_date", "home", "away", "home_goals", "away_goals"]]
    df = df.dropna(subset=["home_goals", "away_goals"])
    df["home_goals"] = df["home_goals"].astype(int)
    df["away_goals"] = df["away_goals"].astype(int)
    return df.sort_values("utc_date").reset_index(drop=True)
