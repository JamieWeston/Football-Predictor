# scripts/sources.py
import os, csv, json
from datetime import datetime, timezone, timedelta
import requests

from .team_names import norm, expand_with_aliases

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")

FD_BASE = "https://api.football-data.org/v4"
FD_COMP_PL = "PL"

def _fd_headers():
    tok = os.getenv("FOOTBALL_DATA_TOKEN", "").strip()
    hdrs = {"Accept": "application/json"}
    if tok: hdrs["X-Auth-Token"] = tok
    return hdrs

def load_team_ratings() -> dict[str, float]:
    """
    Load ratings from data/team_ratings.json OR data/team_ratings.csv.
    Returns: dict keyed by NORMALISED team name.
    """
    js = os.path.join(DATA_DIR, "team_ratings.json")
    cs = os.path.join(DATA_DIR, "team_ratings.csv")

    raw: dict[str, float] = {}

    if os.path.exists(js):
        try:
            with open(js, "r", encoding="utf-8") as f:
                obj = json.load(f)
            for k, v in (obj or {}).items():
                try: raw[k] = float(v)
                except: pass
        except Exception as e:
            print(f"[warn] failed to read JSON ratings: {e}")

    elif os.path.exists(cs):
        try:
            with open(cs, "r", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    k = row.get("team") or row.get("name")
                    v = row.get("rating")
                    if k is None or v is None: continue
                    try:
                        raw[k] = float(v)
                    except:
                        pass
        except Exception as e:
            print(f"[warn] failed to read CSV ratings: {e}")

    if not raw:
        print("[warn] no ratings file found (team_ratings.json or .csv); falling back to zeros")
        return {}

    # normalise + add aliases
    ratings = expand_with_aliases(raw)
    print(f"[info] loaded {len(ratings)} normalised ratings")
    return ratings

def load_fixtures(days_ahead: int | None = None) -> list[dict]:
    """
    Fetch PL fixtures; include yesterday→date_to to catch 'today' correctly.
    """
    if days_ahead is None:
        days_ahead = int(os.getenv("FD_WINDOW_DAYS", "14"))
    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=1)).date().isoformat()
    date_to   = (now + timedelta(days=days_ahead)).date().isoformat()

    url = f"{FD_BASE}/competitions/{FD_COMP_PL}/matches"
    params = {
        "status": "SCHEDULED,TIMED,IN_PLAY",
        "dateFrom": date_from,
        "dateTo": date_to,
    }
    r = requests.get(url, headers=_fd_headers(), params=params, timeout=30)
    r.raise_for_status()
    js = r.json()

    out = []
    for m in js.get("matches", []):
        h = (m.get("homeTeam") or {}).get("name") or (m.get("homeTeam") or {}).get("shortName")
        a = (m.get("awayTeam") or {}).get("name") or (m.get("awayTeam") or {}).get("shortName")
        h_disp = (h or "Home").replace("FC", "").replace("AFC", "").strip()
        a_disp = (a or "Away").replace("FC", "").replace("AFC", "").strip()

        uts = (m.get("utcDate") or "").replace("Z", "+00:00")
        try:
            ko = datetime.fromisoformat(uts)
        except:
            continue

        htla = (m["homeTeam"].get("tla") if m.get("homeTeam") else None) or "".join(w[0] for w in h_disp.split()).upper()
        atla = (m["awayTeam"].get("tla") if m.get("awayTeam") else None) or "".join(w[0] for w in a_disp.split()).upper()
        mid = f"{ko:%Y-%m-%d_%H%M}_{htla}-{atla}"

        out.append({
            "match_id": mid,
            "fd_id": str(m.get("id", "")),
            "home": h_disp,
            "away": a_disp,
            "kickoff_utc": ko.isoformat(),
        })

    out.sort(key=lambda x: x["kickoff_utc"])
    print(f"[fixtures] fetched {len(out)} matches ({date_from}→{date_to})")
    return out

def fetch_best_odds() -> list[dict]:
    return []
