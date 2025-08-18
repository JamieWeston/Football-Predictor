# scripts/generate.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

import pandas as pd

from plpred.fd_client import fetch_fixtures, fetch_results
from plpred.ratings import build_ratings
from plpred.predict import outcome_probs, top_scorelines


DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_results_for_ratings() -> pd.DataFrame:
    """
    Try to load 1–2 recent seasons to build ratings.
    If nothing is available (or token missing), return empty DF → ratings fallback.
    """
    league = os.getenv("FD_LEAGUE", "PL")
    seasons_env = os.getenv("FD_SEASONS", "")  # e.g. "2024,2025"
    seasons: List[int] = []
    for s in (x.strip() for x in seasons_env.split(",") if x.strip()):
        try:
            seasons.append(int(s))
        except ValueError:
            pass

    frames: List[pd.DataFrame] = []
    for s in seasons:
        try:
            df = fetch_results(league, s)
            if not df.empty:
                frames.append(df[["utc_date", "home", "away", "home_goals", "away_goals"]])
        except Exception:
            # Log to console, continue quietly
            print(f"[ratings] WARN could not fetch results for {league} {s}", flush=True)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["utc_date", "home", "away", "home_goals", "away_goals"]
    )


def main() -> None:
    token = os.getenv("FOOTBALL_DATA_TOKEN")
    window_days = int(os.getenv("FD_WINDOW_DAYS", "14"))

    # 1) Results → ratings (robust to empty)
    results_df = _load_results_for_ratings()
    ratings: Dict = build_ratings(results_df)

    # 2) Fixtures window
    fx = fetch_fixtures(days=window_days, token=token)
    if fx.empty:
        print("[generate] No fixtures fetched – nothing to do.")
        return

    # 3) Predict each
    preds = []
    for _, r in fx.iterrows():
        home, away = str(r["home"]), str(r["away"])
        probs = outcome_probs(home, away, ratings)
        preds.append({
            "match_id": str(r.get("match_id")),
            "home": home,
            "away": away,
            "kickoff_utc": str(r.get("utc_date")),
            "xg": {"home": round(probs["mu_h"], 2), "away": round(probs["mu_a"], 2)},
            "probs": {k: round(v, 4) for k, v in probs.items() if k in ("home", "draw", "away")},
            "scorelines_top": top_scorelines(probs["mu_h"], probs["mu_a"], n=3),
            "notes": {"ratings_empty": len(ratings.get("teams", {})) == 0},
        })

    out_json = {
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "predictions": preds,
    }

    # 4) Write outputs
    DATA_DIR.mkdir(exist_ok=True, parents=True)
    (DATA_DIR / "predictions.json").write_text(json.dumps(out_json, indent=2))
    pd.DataFrame(preds).to_csv(DATA_DIR / "predictions.csv", index=False)

    print(f"[generate] wrote {len(preds)} predictions")


if __name__ == "__main__":
    main()
