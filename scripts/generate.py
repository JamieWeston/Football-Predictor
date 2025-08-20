# scripts/generate.py
from __future__ import annotations

import os
import json
import datetime as _dt
from pathlib import Path
from typing import Dict, Any, List
from collections import Counter

import pandas as pd

from plpred.fd_client import fetch_fixtures  # your existing client
from plpred.predict import (
    expected_goals_for_pair,
    outcome_probs,
    top_scorelines,
)


DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(p: Path) -> Any:
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def load_ratings() -> Dict[str, Any]:
    """
    Try to load team ratings with strengths.
    Expected shape:
    {
      "base_home_xg": 1.45,
      "base_away_xg": 1.35,
      "draw_scale": 1.0,
      "teams": {
        "Arsenal": {"att":..., "def":..., "att_h":..., "def_h":..., "att_a":..., "def_a":...},
        ...
      }
    }
    """
    # most recent/complete file first
    for candidate in [
        DATA_DIR / "team_ratings.json",
        DATA_DIR / "team_strengths.json",   # older naming
    ]:
        obj = _read_json(candidate)
        if obj:
            print(f"[gen] loaded ratings from {candidate}")
            return obj

    # Very minimal fallback if nothing exists
    print("[gen] WARNING: no ratings file found; using neutral strengths.")
    return {
        "base_home_xg": 1.45,
        "base_away_xg": 1.35,
        "draw_scale": 1.0,
        "teams": {}
    }


def fetch_fixtures_defensive(days: int = 14) -> pd.DataFrame:
    """
    Call your fd_client in a way that supports both the modern kwargs
    and the older positional signature used in some earlier versions.
    """
    token = os.getenv("FOOTBALL_DATA_TOKEN")
    try:
        # Preferred: rolling window
        fx = fetch_fixtures(days=days, token=token)
    except TypeError:
        # Fallback: legacy signature (session, league, date_from, date_to)
        today = _dt.date.today()
        date_from = today.isoformat()
        date_to = (today + _dt.timedelta(days=days)).isoformat()
        fx = fetch_fixtures(None, "PL", date_from, date_to)

    # Normalise to DataFrame
    if isinstance(fx, list):
        df = pd.DataFrame(fx)
    elif isinstance(fx, pd.DataFrame):
        df = fx.copy()
    else:
        raise RuntimeError("fetch_fixtures returned an unexpected type")

    # Required columns
    need = ["utc_date", "home", "away"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise RuntimeError(f"fixtures missing columns: {missing}")

    # Fill match_id if not set
    if "match_id" not in df.columns or df["match_id"].isna().all():
        df["match_id"] = [
            f"{r['utc_date']}_{(r['home'] or '')[:3]}-{(r['away'] or '')[:3]}"
            for r in df.to_dict("records")
        ]

    return df


def build_predictions(fixtures_df: pd.DataFrame, ratings: Dict[str, Any]) -> Dict[str, Any]:
    preds: List[Dict[str, Any]] = []
    resolve_counts = Counter()
    debug_rows = []

    draw_scale = float(ratings.get("draw_scale", 1.0))

    for row in fixtures_df.to_dict("records"):
        home = row["home"]
        away = row["away"]
        kickoff = row["utc_date"]
        mid = row.get("match_id") or f"{kickoff}_{home[:3]}-{away[:3]}"

        lam_h, lam_a, dbg = expected_goals_for_pair(home, away, ratings)
        ph, pd, pa = outcome_probs(lam_h, lam_a, draw_scale=draw_scale)

        preds.append({
            "match_id": mid,
            "home": home,
            "away": away,
            "kickoff_utc": kickoff,
            "xg": {"home": round(lam_h, 2), "away": round(lam_a, 2)},
            "probs": {"home": round(ph, 4), "draw": round(pd, 4), "away": round(pa, 4)},
            "probs_components": {
                "poisson": {"home": round(ph, 4), "draw": round(pd, 4), "away": round(pa, 4)}
            },
            "scorelines_top": top_scorelines(lam_h, lam_a, k=3, cap=8),
            "notes": {"resolve": {"home": dbg["resolve_home"], "away": dbg["resolve_away"]}},
        })

        resolve_counts[(dbg["resolve_home"], dbg["resolve_away"])] += 1
        debug_rows.append(dbg)

    out = {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "predictions": preds,
    }

    # Extra debug report to help spot unmatched names quickly
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "name_resolution.json").write_text(json.dumps({
        "counts": {f"{k[0]}|{k[1]}": v for k, v in resolve_counts.items()},
        "examples": debug_rows[:50],
    }, indent=2))

    return out


def write_outputs(predictions_obj: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "predictions.json").write_text(json.dumps(predictions_obj, indent=2))
    print("[gen] wrote data/predictions.json")
    print("[gen] wrote reports/name_resolution.json")


def main() -> None:
    ratings = load_ratings()
    fixtures_df = fetch_fixtures_defensive(days=int(os.getenv("FD_WINDOW_DAYS", "14")))
    if fixtures_df.empty:
        print("[gen] WARNING: fixtures are empty; writing empty predictions.")
        write_outputs({"generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(), "predictions": []})
        return

    preds = build_predictions(fixtures_df, ratings)
    write_outputs(preds)


if __name__ == "__main__":
    main()
