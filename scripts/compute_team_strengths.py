# scripts/compute_team_strengths.py
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"

UCSV = DATA / "understat_matches.csv"  # season,date,home,away,home_xg,away_xg,home_goals,away_goals
FCSV = DATA / "fd_results.csv"          # season,date,home_team,away_team,home_goals,away_goals
OUT  = DATA / "team_strengths.json"

MIN_US_ROWS = 500

def _compute_strengths(df: pd.DataFrame, home_col: str, away_col: str,
                       hteam_col: str, ateam_col: str):
    home = df[[hteam_col, home_col]].copy()
    home.columns = ["team", "f"]
    away = df[[ateam_col, away_col]].copy()
    away.columns = ["team", "f"]
    long_for = pd.concat([home, away], ignore_index=True)

    home_a = df[[ateam_col, home_col]].copy()
    home_a.columns = ["team", "a"]
    away_a = df[[hteam_col, away_col]].copy()
    away_a.columns = ["team", "a"]
    long_against = pd.concat([home_a, away_a], ignore_index=True)

    long = long_for.join(long_against["a"])

    league_for = long["f"].mean() or 1.0
    league_against = long["a"].mean() or 1.0

    per_team = long.groupby("team").agg(matches=("f", "count"),
                                        f=("f", "mean"),
                                        a=("a", "mean"))
    per_team["attack"] = per_team["f"] / league_for
    per_team["defence"] = per_team["a"] / league_against

    return per_team[["matches", "attack", "defence"]].sort_index()

def main():
    use = None
    metric = None

    if UCSV.exists():
        try:
            us = pd.read_csv(UCSV)
            if len(us) >= MIN_US_ROWS:
                strengths = _compute_strengths(us,
                                               home_col="home_xg",
                                               away_col="away_xg",
                                               hteam_col="home",
                                               ateam_col="away")
                use, metric = "understat", "xg"
            else:
                print(f"[strengths] Understat rows={len(us)} (<{MIN_US_ROWS}) – fallback to football-data")
        except Exception as e:
            print(f"[strengths] Understat read failed: {e}")

    if use is None:
        if not FCSV.exists():
            raise SystemExit("[strengths] fd_results.csv missing – cannot fallback")
        fd = pd.read_csv(FCSV)
        strengths = _compute_strengths(fd,
                                       home_col="home_goals",
                                       away_col="away_goals",
                                       hteam_col="home_team",
                                       ateam_col="away_team")
        use, metric = "football-data", "goals"

    out = {
        "source": use,
        "metric": metric,
        "updated_utc": pd.Timestamp.utcnow().isoformat(),
        "teams": strengths[["attack", "defence"]].round(4).to_dict(orient="index"),
    }
    OUT.write_text(json.dumps(out, indent=2))
    print(f"[strengths] wrote {OUT} ({len(out['teams'])} teams)")

if __name__ == "__main__":
    main()
