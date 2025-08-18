# scripts/fetch_understat_xg.py
import os
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timezone
from understat import Understat

OUT_CSV = "data/understat_matches.csv"
LEAGUE = "epl"  # Understat slug
# Comma-separated list in env, newest last so the most recent season is last
SEASONS = [s.strip() for s in os.getenv("US_SEASONS", "2023,2024,2025").split(",") if s.strip()]

async def _fetch():
    os.makedirs("data", exist_ok=True)
    rows = []
    async with aiohttp.ClientSession() as session:
        u = Understat(session)
        for season in SEASONS:
            teams = await u.get_teams(LEAGUE, season)
            for t in teams:
                tid = t["id"]
                name = t["title"]
                # Team results contain xG/xGA per match, plus H/A, date, goals
                res = await u.get_team_results(tid, season)
                for m in res:
                    try:
                        date_utc = datetime.fromisoformat(m["datetime"]).replace(tzinfo=timezone.utc)
                    except Exception:
                        date_utc = datetime.strptime(m["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    row = dict(
                        season=int(season),
                        match_id=int(m["id"]),
                        date_utc=date_utc.isoformat(),
                        side="home" if m["h_a"] == "h" else "away",
                        team=name,
                        opponent=m["opponent"],
                        goals_for=float(m["goals"]),
                        goals_against=float(m["goals_against"]),
                        xg_for=float(m["xG"]),
                        xg_against=float(m["xGA"]),
                        home=1 if m["h_a"] == "h" else 0,
                    )
                    rows.append(row)

    df = pd.DataFrame(rows)
    # Build one row per match (merge home/away rows)
    # Key by match_id; pivot the two sides onto home/away
    # Keep only Premier League (Understat results here are already league matches)
    # Build tidy output
    # First, pick home and away rows
    homes = df[df["home"] == 1].copy()
    aways = df[df["home"] == 0].copy()
    homes = homes.add_prefix("h_")
    aways = aways.add_prefix("a_")
    merged = pd.merge(homes, aways, left_on="h_match_id", right_on="a_match_id", how="inner")

    out = pd.DataFrame({
        "match_id": merged["h_match_id"].astype(int),
        "season": merged["h_season"].astype(int),
        "date_utc": merged["h_date_utc"],
        "home_team": merged["h_team"],
        "away_team": merged["a_team"],
        "home_goals": merged["h_goals_for"].astype(float),
        "away_goals": merged["a_goals_for"].astype(float),
        "home_xg": merged["h_xg_for"].astype(float),
        "away_xg": merged["a_xg_for"].astype(float),
    }).drop_duplicates("match_id").sort_values("date_utc")

    out.to_csv(OUT_CSV, index=False)
    print(f"[understat] wrote {len(out)} rows -> {OUT_CSV}")

def main():
    asyncio.run(_fetch())

if __name__ == "__main__":
    main()
