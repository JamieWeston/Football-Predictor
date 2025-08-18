# scripts/compute_team_strengths.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Tuple, Dict, Any
import pandas as pd


U_PATH = Path("data/understat_matches.csv")
FD_PATH = Path("data/fd_results.csv")
OUT_PATH = Path("data/team_strengths.json")


def _load_dataset() -> Tuple[pd.DataFrame, str]:
    """
    Prefer Understat if present and has sufficient rows; else fall back to FD results.
    Returns (normalized_df, source_name)
    Columns on return: home, away, goals_h, goals_a, xg_h (optional), xg_a (optional)
    """
    if U_PATH.exists():
        u = pd.read_csv(U_PATH)
        if len(u) > 500:
            df = u.rename(
                columns={
                    "date": "date",
                    "home": "home",
                    "away": "away",
                    "goals_h": "goals_h",
                    "goals_a": "goals_a",
                    "xg_h": "xg_h",
                    "xg_a": "xg_a",
                }
            ).copy()
            print(f"[strengths] using Understat ({len(df)} rows)")
            return df, "understat"
        else:
            print(f"[strengths] Understat present but too small ({len(u)} rows)")

    if FD_PATH.exists():
        f = pd.read_csv(FD_PATH)
        if len(f) > 300:
            df = f.rename(
                columns={
                    "date": "date",
                    "home": "home",
                    "away": "away",
                    "goals_h": "goals_h",
                    "goals_a": "goals_a",
                }
            ).copy()
            print(f"[strengths] using football-data ({len(df)} rows)")
            return df, "fd"
        else:
            print(f"[strengths] football-data present but too small ({len(f)} rows)")

    raise SystemExit(
        "[strengths] No usable dataset found. "
        "Expected data/understat_matches.csv (>500 rows) or data/fd_results.csv (>300 rows)."
    )


def _compute_strengths(df: pd.DataFrame) -> Dict[str, Any]:
    # prefer xG if available
    use_xg = "xg_h" in df.columns and "xg_a" in df.columns and df["xg_h"].notna().any()

    if use_xg:
        h_for = df["xg_h"].astype(float)
        a_for = df["xg_a"].astype(float)
    else:
        h_for = df["goals_h"].astype(float)
        a_for = df["goals_a"].astype(float)

    total_matches = len(df)
    total_home_for = h_for.sum()
    total_away_for = a_for.sum()

    # league averages per team per game
    league_for_pg = (total_home_for + total_away_for) / (2.0 * total_matches)
    # home advantage factor: home_for_per_game / away_for_per_game
    home_for_pg = total_home_for / total_matches
    away_for_pg = total_away_for / total_matches
    home_adv = max(0.9, min(1.3, (home_for_pg / max(away_for_pg, 1e-9))))

    # build per-team numbers
    teams = {}
    teams_list = pd.unique(pd.concat([df["home"], df["away"]], ignore_index=True))
    for t in teams_list:
        home_rows = df["home"] == t
        away_rows = df["away"] == t

        if use_xg:
            gf = h_for[home_rows].sum() + a_for[away_rows].sum()
            ga = a_for[home_rows].sum() + h_for[away_rows].sum()
        else:
            gf = df.loc[home_rows, "goals_h"].sum() + df.loc[away_rows, "goals_a"].sum()
            ga = df.loc[home_rows, "goals_a"].sum() + df.loc[away_rows, "goals_h"].sum()

        gp = home_rows.sum() + away_rows.sum()
        if gp == 0:
            continue

        gf_pg = gf / gp
        ga_pg = ga / gp

        attack = float(gf_pg / max(league_for_pg, 1e-9))
        defense = float(ga_pg / max(league_for_pg, 1e-9))  # <1 is better

        teams[str(t)] = {
            "attack": attack,
            "defense": defense,
            # keep aliases some generator variants expect
            "att": attack,
            "def": defense,
        }

    return {
        "home_adv": float(home_adv),
        "teams": teams,
        "n_matches": int(total_matches),
        "metric": "xg" if use_xg else "goals",
    }


def main():
    df, source = _load_dataset()
    strengths = _compute_strengths(df)
    strengths["source"] = source
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(strengths, f, indent=2)
    print(f"[strengths] wrote {OUT_PATH} (teams={len(strengths['teams'])}, source={source})")


if __name__ == "__main__":
    main()
