from __future__ import annotations
import json, os
from pathlib import Path
import pandas as pd
from plpred import log as logmod
from plpred.ratings import build_ratings
from plpred.elo import build_elo

def main() -> None:
    logmod.setup()
    Path("data").mkdir(parents=True, exist_ok=True)

    half_life_days = float(os.getenv("HALF_LIFE_DAYS", "180"))

    p = Path("data/fd_results.csv")
    if p.exists():
        df = pd.read_csv(p)
    else:
        print("[core_build_ratings] WARN: fd_results.csv missing; using empty frame.")
        df = pd.DataFrame(columns=["utc_date","home","away","home_goals","away_goals"])

    ratings = build_ratings(df, half_life_days=half_life_days)
    Path("data/team_strengths.json").write_text(json.dumps(ratings, indent=2))
    print("[core_build_ratings] wrote data/team_strengths.json teams:", len(ratings.get("teams", {})))

    elo = build_elo(df, half_life_days=max(half_life_days, 120.0))
    Path("data/elo_ratings.json").write_text(json.dumps(elo, indent=2))
    print("[core_build_ratings] wrote data/elo_ratings.json teams:", len(elo.get("teams", {})))

if __name__ == "__main__":
    main()
