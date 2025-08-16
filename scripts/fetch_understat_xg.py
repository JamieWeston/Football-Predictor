# scripts/fetch_understat_xg.py
import os, json, asyncio
from datetime import datetime
from understat import Understat
import aiohttp
from scripts.team_names import norm

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "understat_team_matches.json")

# Map league code and seasons we want (Understat uses numeric season like "2023", "2024", "2025")
LEAGUE = "epl"
SEASONS = ["2023", "2024", "2025"]  # last 3 seasons including current

async def _fetch():
    out_rows = []
    async with aiohttp.ClientSession() as session:
        u = Understat(session)
        teams = await u.get_teams(LEAGUE)
        # teams: list of dicts with id, title, etc.
        for t in teams:
            tid = t["id"]
            tname = t["title"]
            tnorm = norm(tname)
            for season in SEASONS:
                # get team matches for season (contains xG, xGA, home/away, date, opponent, result)
                matches = await u.get_team_results(tid, season)
                # normalize
                for m in matches:
                    try:
                        date_str = m["datetime"][:10] if "datetime" in m else m["date"]
                        ko = datetime.fromisoformat(date_str)
                    except Exception:
                        # try simple fallback
                        try:
                            ko = datetime.strptime(m["date"], "%Y-%m-%d")
                        except Exception:
                            continue
                    out_rows.append({
                        "team": tname,
                        "team_norm": tnorm,
                        "season": season,
                        "date": ko.strftime("%Y-%m-%d"),
                        "is_home": bool(m.get("h_a") == "h"),
                        "opponent": m.get("opponent") or "",
                        "opponent_norm": norm(m.get("opponent") or ""),
                        "xg_for": float(m.get("xG", 0.0)),
                        "xg_against": float(m.get("xGA", 0.0)),
                        "scored": int(m.get("scored", 0)),
                        "conceded": int(m.get("conceded", 0))
                    })
                # small polite pause
        return out_rows

def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    rows = asyncio.run(_fetch())
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"rows": rows}, f, indent=2)
    print(f"[understat] wrote {len(rows)} rows to {OUT}")

if __name__ == "__main__":
    main()
