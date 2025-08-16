# scripts/sources.py
import os
import csv
from datetime import datetime, timedelta, timezone
import requests

# --- Team name normalisation (reduce mismatches) ---
ALIASES = {
    "Wolverhampton Wanderers": "Wolves",
    "Wolverhampton": "Wolves",
    "Brighton & Hove Albion": "Brighton",
    "AFC Bournemouth": "Bournemouth",
    "Nott'ham Forest": "Nottingham Forest",
    "Nottingham Forest FC": "Nottingham Forest",
    "Manchester City FC": "Manchester City",
    "Manchester United FC": "Manchester United",
    "Newcastle United FC": "Newcastle United",
    "Tottenham Hotspur FC": "Tottenham Hotspur",
    "Chelsea FC": "Chelsea",
    "Arsenal FC": "Arsenal",
    "Liverpool FC": "Liverpool",
    "Everton FC": "Everton",
    "Aston Villa FC": "Aston Villa",
    "West Ham United FC": "West Ham United",
    "Crystal Palace FC": "Crystal Palace",
    "Brentford FC": "Brentford",
    "Fulham FC": "Fulham",
    "Leeds United FC": "Leeds United",
    "Leicester City FC": "Leicester City",
    "Southampton FC": "Southampton",
    "Burnley FC": "Burnley",
    "Ipswich Town FC": "Ipswich Town",
}

def _norm(name: str) -> str:
    if not name:
        return "Unknown"
    n = name.replace(" FC", "").replace(" A.F.C.", "").strip()
    return ALIASES.get(n, n)

def _abbr(name: str) -> str:
    parts = _norm(name).split()
    if len(parts) == 1:
        return parts[0][:3].upper()
    # simple 2–3 letter code
    last = parts[-1]
    return (parts[0][0] + last[0] + (last[1] if len(last) > 1 else "")).upper()

# --- Public functions used by your scripts ---

def load_team_ratings():
    """
    Read data/team_ratings.csv if present (fallback to 0.0 for all teams).
    CSV format: team,rating
    """
    out = {}
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, "data", "team_ratings.csv")
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            team = row.get("team") or row.get("name") or ""
            try:
                rating = float(row.get("rating", "0") or "0")
            except Exception:
                rating = 0.0
            out[_norm(team)] = rating
    return out


def load_fixtures():
    """
    Fetch PL fixtures from football-data.org covering:
      - start: yesterday (UTC)  → catches early-UTC 'today' games
      - end:   now + FD_WINDOW_DAYS (default 14)
    Include statuses: SCHEDULED, TIMED, IN_PLAY (so 'today' still shows if a match just kicked off).
    Return list of dicts: { match_id, fd_id, home, away, kickoff_utc } sorted by kickoff.
    """
    token = os.getenv("FOOTBALL_DATA_TOKEN", "").strip()
    if not token:
        raise RuntimeError("FOOTBALL_DATA_TOKEN is not set")

    now = datetime.now(timezone.utc)
    days_ahead = int(os.getenv("FD_WINDOW_DAYS", "14"))
    date_from = (now - timedelta(days=1)).date().isoformat()  # <— include yesterday
    date_to   = (now + timedelta(days=days_ahead)).date().isoformat()

    url = (
        "https://api.football-data.org/v4/competitions/PL/matches"
        f"?dateFrom={date_from}&dateTo={date_to}&status=SCHEDULED,TIMED,IN_PLAY"
    )
    resp = requests.get(
        url,
        headers={"X-Auth-Token": token, "Accept": "application/json"},
        timeout=30
    )
    resp.raise_for_status()
    matches = resp.json().get("matches", []) or []

    out = []
    for m in matches:
        fd_id = str(m.get("id", ""))
        utc = (m.get("utcDate") or "").replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(utc)
        except Exception:
            continue
        hname = _norm((m.get("homeTeam") or {}).get("name", "Home"))
        aname = _norm((m.get("awayTeam") or {}).get("name", "Away"))

        match_id = f"{dt.date().isoformat()}_{dt.strftime('%H%M')}_{_abbr(hname)}-{_abbr(aname)}"
        out.append({
            "match_id": match_id,
            "fd_id": fd_id,
            "home": hname,
            "away": aname,
            "kickoff_utc": dt.isoformat(),
        })

    out.sort(key=lambda x: x["kickoff_utc"])
    print(f"[fixtures] fetched {len(out)} between {date_from} and {date_to} (statuses SCHEDULED/TIMED/IN_PLAY)")
    return out


def fetch_best_odds():
    """
    Placeholder. Returns empty list (you said no odds for now).
    When ready, populate with [{match_id, market, selection, decimal_odds, source}, ...].
    """
    return []
