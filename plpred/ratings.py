# plpred/ratings.py
from __future__ import annotations

from typing import Dict
import pandas as pd
import numpy as np


def _safe_ratio(num: float, den: float, default: float = 0.0) -> float:
    if den is None or den == 0:
        return default
    return float(num) / float(den)


def build_ratings(
    matches: pd.DataFrame,
    half_life_days: float | None = None,  # accepted but not required for now
) -> Dict[str, Dict[str, float]]:
    """
    Compute simple per-team attack/defence strength factors from a matches DataFrame.

    Expected columns in `matches` (strings OK for utc_date):
      - 'utc_date' (optional), 'home', 'away', 'home_goals', 'away_goals'

    Returns
    -------
    Dict[team, Dict[str, float]] with keys:
      'att', 'def', 'att_h', 'def_h', 'att_a', 'def_a'
    """
    if matches is None or len(matches) == 0:
        return {}

    df = matches.copy()

    # Normalize columns that matter.
    required = {"home", "away", "home_goals", "away_goals"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"build_ratings: missing columns {sorted(missing)}")

    # Ensure numeric
    for c in ("home_goals", "away_goals"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

    # --- Aggregate home and away separately with an explicit 'team' column ---
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

    # Outer join so teams that only played home or away are included.
    base = (
        pd.merge(home_stats, away_stats, on="team", how="outer")
        .fillna(0)
        .astype(
            {"gf_h": int, "ga_h": int, "gp_h": int, "gf_a": int, "ga_a": int, "gp_a": int}
        )
    )

    # Totals
    base["gf"] = base["gf_h"] + base["gf_a"]
    base["ga"] = base["ga_h"] + base["ga_a"]
    base["gp"] = base["gp_h"] + base["gp_a"]

    # League baselines (goals per game). Guard against 0.
    lg_h_scored = _safe_ratio(base["gf_h"].sum(), base["gp_h"].sum(), default=1.0)
    lg_h_conceded = _safe_ratio(base["ga_h"].sum(), base["gp_h"].sum(), default=1.0)

    lg_a_scored = _safe_ratio(base["gf_a"].sum(), base["gp_a"].sum(), default=1.0)
    lg_a_conceded = _safe_ratio(base["ga_a"].sum(), base["gp_a"].sum(), default=1.0)

    lg_all_scored = _safe_ratio(base["gf"].sum(), base["gp"].sum(), default=1.0)
    lg_all_conceded = _safe_ratio(base["ga"].sum(), base["gp"].sum(), default=1.0)

    # Compute factors; if gp_* = 0 we fall back to 1.0 (neutral strength).
    ratings: Dict[str, Dict[str, float]] = {}

    for _, row in base.iterrows():
        team = row["team"]

        # Home attack/defence vs league
        att_h = _safe_ratio(_safe_ratio(row["gf_h"], row["gp_h"], default=0.0), lg_h_scored, default=1.0) or 1.0
        def_h = _safe_ratio(_safe_ratio(row["ga_h"], row["gp_h"], default=0.0), lg_h_conceded, default=1.0) or 1.0

        # Away attack/defence vs league
        att_a = _safe_ratio(_safe_ratio(row["gf_a"], row["gp_a"], default=0.0), lg_a_scored, default=1.0) or 1.0
        def_a = _safe_ratio(_safe_ratio(row["ga_a"], row["gp_a"], default=0.0), lg_a_conceded, default=1.0) or 1.0

        # Overall attack/defence vs league
        att = _safe_ratio(_safe_ratio(row["gf"], row["gp"], default=0.0), lg_all_scored, default=1.0) or 1.0
        dfn = _safe_ratio(_safe_ratio(row["ga"], row["gp"], default=0.0), lg_all_conceded, default=1.0) or 1.0

        ratings[team] = {
            "att": float(att),
            "def": float(dfn),
            "att_h": float(att_h),
            "def_h": float(def_h),
            "att_a": float(att_a),
            "def_a": float(def_a),
        }

    return ratings
