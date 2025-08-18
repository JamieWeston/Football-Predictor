# plpred/ratings.py
from __future__ import annotations

from typing import Dict, Any
import pandas as pd


def _safe_ratio(num: float, den: float, default: float) -> float:
    try:
        if den and den != 0:
            return float(num) / float(den)
    except Exception:
        pass
    return float(default)


def build_ratings(
    matches: pd.DataFrame,
    half_life_days: float | None = None,  # accepted for future weighting, unused here
) -> Dict[str, Any]:
    """
    Compute simple per-team attack/defence factors from a matches DataFrame and
    return a summary dict with league context.

    Expected columns in `matches`:
      - 'home', 'away', 'home_goals', 'away_goals'
        (extra columns like 'utc_date' are ignored)

    Returns
    -------
    {
      "teams": {
        <team>: {
          "att":   float,  # overall attacking strength vs league avg (goals for / g)
          "def":   float,  # overall defensive factor vs league avg (goals against / g)
          "att_h": float,  # home attacking factor vs league home avg
          "def_h": float,  # home defensive factor vs league home avg
          "att_a": float,  # away attacking factor vs league away avg
          "def_a": float,  # away defensive factor vs league away avg
        },
        ...
      },
      "league_avg_gpg": float,  # league-wide goals per game
      "home_adv": float         # multiplicative home advantage (>= 1.0)
    }
    """
    # Empty or None → neutral baseline summary
    if matches is None or len(matches) == 0:
        return {
            "teams": {},
            "league_avg_gpg": 2.60,  # safe, realistic default
            "home_adv": 1.05,        # mild home edge default
        }

    df = matches.copy()

    required = {"home", "away", "home_goals", "away_goals"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"build_ratings: missing columns {sorted(missing)}")

    # Ensure numeric ints for goals
    for c in ("home_goals", "away_goals"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

    # --- Aggregate home and away with explicit 'team' column ---
    home_stats = (
        df.groupby("home", dropna=False)
        .agg(
            gf_h=("home_goals", "sum"),
            ga_h=("away_goals", "sum"),
            gp_h=("home_goals", "size"),
        )
        .rename_axis("team")
        .reset_index()
    )

    away_stats = (
        df.groupby("away", dropna=False)
        .agg(
            gf_a=("away_goals", "sum"),
            ga_a=("home_goals", "sum"),
            gp_a=("away_goals", "size"),
        )
        .rename_axis("team")
        .reset_index()
    )

    # Outer join ensures teams with only home or only away games are included
    base = home_stats.merge(away_stats, on="team", how="outer").fillna(0)
    # integer-cast the counts/sums we created
    for c in ("gf_h", "ga_h", "gp_h", "gf_a", "ga_a", "gp_a"):
        base[c] = base[c].astype(int)

    # Totals
    base["gf"] = base["gf_h"] + base["gf_a"]
    base["ga"] = base["ga_h"] + base["ga_a"]
    base["gp"] = base["gp_h"] + base["gp_a"]

    # League baselines (guarded)
    lg_gp_h = int(base["gp_h"].sum())
    lg_gp_a = int(base["gp_a"].sum())
    lg_gp_all = int(base["gp"].sum())

    lg_h_scored = _safe_ratio(base["gf_h"].sum(), lg_gp_h, default=1.30)   # ~typical home GPG
    lg_a_scored = _safe_ratio(base["gf_a"].sum(), lg_gp_a, default=1.30)   # ~typical away GPG
    lg_all_scored = _safe_ratio(base["gf"].sum(), lg_gp_all, default=2.60) # league GPG

    # Home advantage as a multiplicative factor on scoring rate
    home_adv = _safe_ratio(lg_h_scored, lg_a_scored, default=1.05)
    if home_adv < 1.0:
        # Keep it ≥1.0 as the tests expect; clamp very small samples
        home_adv = 1.0

    teams: Dict[str, Dict[str, float]] = {}

    for _, row in base.iterrows():
        team = row["team"]

        # Per-team per-game rates (guard against zero games)
        r_h_gpg_for = _safe_ratio(row["gf_h"], row["gp_h"], default=0.0)
        r_h_gpg_against = _safe_ratio(row["ga_h"], row["gp_h"], default=0.0)
        r_a_gpg_for = _safe_ratio(row["gf_a"], row["gp_a"], default=0.0)
        r_a_gpg_against = _safe_ratio(row["ga_a"], row["gp_a"], default=0.0)
        r_all_gpg_for = _safe_ratio(row["gf"], row["gp"], default=0.0)
        r_all_gpg_against = _safe_ratio(row["ga"], row["gp"], default=0.0)

        # Factors vs league baselines; fall back to 1.0 if denominator is unknown
        att_h = _safe_ratio(r_h_gpg_for, lg_h_scored, default=1.0) or 1.0
        def_h = _safe_ratio(r_h_gpg_against, lg_h_scored, default=1.0) or 1.0

        att_a = _safe_ratio(r_a_gpg_for, lg_a_scored, default=1.0) or 1.0
        def_a = _safe_ratio(r_a_gpg_against, lg_a_scored, default=1.0) or 1.0

        att = _safe_ratio(r_all_gpg_for, lg_all_scored, default=1.0) or 1.0
        dfn = _safe_ratio(r_all_gpg_against, lg_all_scored, default=1.0) or 1.0

        teams[team] = {
            "att": float(att),
            "def": float(dfn),
            "att_h": float(att_h),
            "def_h": float(def_h),
            "att_a": float(att_a),
            "def_a": float(def_a),
        }

    return {
        "teams": teams,
        "league_avg_gpg": float(lg_all_scored if lg_all_scored > 0 else 2.60),
        "home_adv": float(home_adv),
    }
