#!/usr/bin/env python3
"""
Compute team attack/defence strengths.

Priority:
1) If data/understat_matches.csv exists and has enough rows, use it
   (xG if present, else goals).
2) Else if data/fd_results.csv exists, use that (goals).
3) Else emit a conservative baseline so the pipeline never hard-fails.

Outputs: data/team_strengths.json
"""

import json
from pathlib import Path
import pandas as pd

US_CSV = Path("data/understat_matches.csv")
FD_CSV = Path("data/fd_results.csv")
OUT = Path("data/team_strengths.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

MIN_US_ROWS = 500          # require a decent sample to trust Understat
MIN_FD_ROWS = 200          # about 5–6 rounds

def _strengths_from_goals(df, home_col, away_col, hg_col, ag_col):
    # Long format
    home = df[[home_col, hg_col, ag_col]].copy()
    home.columns = ["team", "gf", "ga"]
    away = df[[away_col, hg_col, ag_col]].copy()
    away.columns = ["opp", "ga", "gf"]          # invert and rename
    away = away.rename(columns={"opp": "team"})
    long = pd.concat([home, away], ignore_index=True)

    long["matches"] = 1
    agg = long.groupby("team", as_index=False)[["gf", "ga", "matches"]].sum()

    # League averages
    lg_gf_per_match = agg["gf"].sum() / agg["matches"].sum()
    lg_ga_per_match = agg["ga"].sum() / agg["matches"].sum()

    # Attack/defence factors (relative to league average)
    agg["att"] = (agg["gf"] / agg["matches"]) / max(lg_gf_per_match, 1e-6)
    agg["def"] = (agg["ga"] / agg["matches"]) / max(lg_ga_per_match, 1e-6)

    # Clamp to avoid extreme values early in the season
    agg["att"] = agg["att"].clip(0.6, 1.6)
    agg["def"] = agg["def"].clip(0.6, 1.6)

    return {
        row["team"]: {
            "att": round(float(row["att"]), 4),
            "def": round(float(row["def"]), 4),
            "matches": int(row["matches"]),
            "gf": round(float(row["gf"]), 1),
            "ga": round(float(row["ga"]), 1),
        }
        for _, row in agg.iterrows()
    }

def _load_understat():
    if not US_CSV.exists():
        return None
    df = pd.read_csv(US_CSV)
    if len(df) < MIN_US_ROWS:
        print(f"[strengths] Understat present but too few rows ({len(df)} < {MIN_US_ROWS})")
        return None

    # Prefer xG columns if present; fall back to goals
    h_xg = next((c for c in df.columns if c.lower() in {"xg_home", "home_xg", "hxg"}), None)
    a_xg = next((c for c in df.columns if c.lower() in {"xg_away", "away_xg", "axg"}), None)
    h = next((c for c in df.columns if c.lower() in {"home", "home_team", "team_home"}), None)
    a = next((c for c in df.columns if c.lower() in {"away", "away_team", "team_away"}), None)
    hg = next((c for c in df.columns if c.lower() in {"home_goals", "hg", "fthg"}), None)
    ag = next((c for c in df.columns if c.lower() in {"away_goals", "ag", "ftag"}), None)

    if h_xg and a_xg and h and a:
        # Use expected goals
        tmp = df[[h, a, h_xg, a_xg]].copy()
        tmp.columns = ["home", "away", "home_goals", "away_goals"]
        print(f"[strengths] using Understat xG ({len(tmp)} rows)")
        return _strengths_from_goals(tmp, "home", "away", "home_goals", "away_goals")

    if h and a and hg and ag:
        tmp = df[[h, a, hg, ag]].copy()
        tmp.columns = ["home", "away", "home_goals", "away_goals"]
        print(f"[strengths] using Understat goals ({len(tmp)} rows)")
        return _strengths_from_goals(tmp, "home", "away", "home_goals", "away_goals")

    print("[strengths] Understat format not recognised – skipping")
    return None

def _load_fd():
    if not FD_CSV.exists():
        print("[strengths] fd_results.csv missing – fallback unavailable")
        return None
    df = pd.read_csv(FD_CSV)
    if len(df) < MIN_FD_ROWS:
        print(f"[strengths] fd_results.csv too small ({len(df)} < {MIN_FD_ROWS}) – skipping")
        return None
    print(f"[strengths] using football-data results ({len(df)} rows)")
    return _strengths_from_goals(df, "home", "away", "home_goals", "away_goals")

def _baseline():
    print("[strengths] emitting conservative baseline (att=def=1.0)")
    return {}

def main():
    strengths = _load_understat()
    if strengths is None:
        strengths = _load_fd()
    if strengths is None:
        strengths = _baseline()

    OUT.write_text(json.dumps({"teams": strengths}, indent=2))
    print(f"[strengths] wrote {OUT} with {len(strengths)} teams")

if __name__ == "__main__":
    main()
