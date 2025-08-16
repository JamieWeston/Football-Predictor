import os
import json
import requests
from datetime import datetime, timedelta, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Map provider names to your ratings keys in data/team_ratings.csv
ALIASES = {
    # exact differences between API and your ratings file
    "Wolverhampton Wanderers": "Wolves",
    "Wolverhampton": "Wolves",
    "Brighton & Hove Albion": "Brighton",
    "AFC Bournemouth": "Bournemouth",
    "Nott'ham Forest": "Nottingham Forest",  # sometimes used by some feeds
    "Man City": "Manchester City",
    "Manchester City FC": "Manchester City",
    "Man United": "Manchester United",
    "Manchester Utd": "Manchester United",
    # add more if needed
}

def normalize_team(name: str, tla: str | None = None) -> str:
    """Return the team name as used in your ratings file."""
    if not name:
        return tla or "Unknown"
    # strip common suffixes
    nm = name.replace(" FC", "").replace(" A.F.C.", "").strip()
    return ALIASES.get(nm, nm)

def load_fixtures():
    """
    Fetch upcoming Premier League fixtures from football-data.org.
    Falls back to data/fixtures.json if API is unavailable/misconfigured.
    Controlled by:
      - FOOTBALL_DATA_TOKEN (secret)
      - FD_WINDOW_DAYS (env, default 10)
    """
    token = os.getenv("FOOTBALL_DATA_TOKEN", "").strip()
    window_days = int(os.getenv("FD_WINDOW_DAYS", "10"))

    if token:
        try:
            now = datetime.now(timezone.utc)
            date_from = now.date().isoformat()
            date_to = (now + timedelta(days=window_days)).date().isoformat()

            url = (
                "https://api.football-data.org/v4/competitions/PL/matches"
                f"?status=SCHEDULED&dateFrom={date_from}&dateTo={date_to}"
            )
            headers = {
                "X-Auth-Token": token,
                "Accept": "application/json",
            }
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            matches = payload.get("matches", [])

            out, seen = [], set()
            for m in matches:
                utc = m.get("utcDate")
                if not utc:
                    continue

                h = m.get("homeTeam", {}) or {}
                a = m.get("awayTeam", {}) or {}
                home_name = h.get("name") or h.get("shortName") or h.get("tla") or "Home"
                away_name = a.get("name") or a.get("shortName") or a.get("tla") or "Away"
                home_tla = h.get("tla") or (home_name[:3].upper() if home_name else "HOM")
                away_tla = a.get("tla") or (away_name[:3].upper() if away_name else "AWY")

                home = normalize_team(home_name, home_tla)
                away = normalize_team(away_name, away_tla)

                # Build a stable match_id like YYYY-MM-DD_HHMM_TLA-TLA
                try:
                    dt = datetime.fromisoformat(utc.replace("Z", "+00:00"))
                    hhmm = dt.strftime("%H%M")
                    mid = f"{dt.date()}_{hhmm}_{home_tla}-{away_tla}"
                except Exception:
                    mid = f"{utc[:10]}_{utc[11:16].replace(':','')}_{home_tla}-{away_tla}"

                if mid in seen:
                    continue
                seen.add(mid)

                kickoff_utc = utc if utc.endswith("Z") else utc + "Z"
                out.append({
                    "match_id": mid,
                    "kickoff_utc": kickoff_utc,
                    "home": home,
                    "away": away
                })

            if out:
                out.sort(key=lambda x: x["kickoff_utc"])
                print(f"[fixtures] fetched {len(out)} fixtures from football-data.org ({date_from}→{date_to})")
                return out

        except Exception as e:
            print(f"[fixtures] API fetch failed; using fallback. Error: {e}")

    # Fallback to local file
    try:
        with open(os.path.join(DATA_DIR, "fixtures.json"), "r") as f:
            data = json.load(f)
            fixtures = data.get("fixtures", [])
            print(f"[fixtures] using fallback fixtures.json ({len(fixtures)})")
            return fixtures
    except Exception as e:
        print(f"[fixtures] no fallback found: {e}")
        return []

def load_team_ratings():
    """Read data/team_ratings.csv and compute z-scores as ratings."""
    import csv
    ratings = {}
    with open(os.path.join(DATA_DIR, "team_ratings.csv"), newline="") as f:
        reader = csv.DictReader(f)
        vals = [float(r["ExpPts"]) for r in reader]
        f.seek(0); reader = csv.DictReader(f)
        mu = sum(vals)/len(vals)
        sd = (sum((v-mu)**2 for v in vals)/len(vals))**0.5
        for row in reader:
            name = row["Team"].strip()
            ratings[name] = (float(row["ExpPts"]) - mu) / sd if sd > 0 else 0.0
    return ratings

def fetch_best_odds():
    """Not used yet. Keep empty so the generator never waits on odds."""
    return []
