# scripts/generate.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any

import pandas as pd

# Local package imports (repo root is on PYTHONPATH in the workflow)
from plpred.fd_client import fetch_fixtures, fetch_results
from plpred.ratings import build_ratings
from plpred.elo import build_elo, elo_match_probs
from plpred.predict import outcome_probs, top_scorelines


DATA_DIR = Path("data")
OUT_JSON = DATA_DIR / "predictions.json"


def _abbr(name: str) -> str:
    """Very small slug for match_id."""
    if not name:
        return "UNK"
    # take first 3 alnum characters across words
    s = "".join(ch for ch in name if ch.isalnum())
    return (s[:3] or "UNK")


def _team(ratings: Dict[str, Any], team: str) -> Dict[str, float]:
    return ratings.get("teams", {}).get(team, {})


def _expected_goals(ratings: Dict[str, Any], home: str, away: str) -> Dict[str, float]:
    """
    Conservative expected-goals estimate using team attack/defence splits.
    Keeps defaults (1.35 / 1.15) if ratings are thin.
    """
    th = _team(ratings, home)
    ta = _team(ratings, away)

    # sensible league baselines
    base_h, base_a = 1.35, 1.15
    # use splits if available, else fall back to neutral att/def (1.0)
    lam_h = base_h * float(th.get("att_h", th.get("att", 1.0))) * float(ta.get("def_a", ta.get("def", 1.0)))
    lam_a = base_a * float(ta.get("att_a", ta.get("att", 1.0))) * float(th.get("def_h", th.get("def", 1.0)))
    return {"home": round(max(lam_h, 0.05), 2), "away": round(max(lam_a, 0.05), 2)}


def main() -> None:
    # --- configuration via env ---
    token = os.getenv("FOOTBALL_DATA_TOKEN", "")
    window_days = int(os.getenv("FD_WINDOW_DAYS", "14"))       # future fixtures span
    lookback_days = int(os.getenv("FD_LOOKBACK_DAYS", "365"))  # historical window
    blend_elo = float(os.getenv("BLEND_ELO", "0.40"))          # 0..1 weight for ELO in the blend

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # --- fetch input data (POSitional calls – no keyword names) ---
    fixtures = fetch_fixtures(window_days, token)          # <-- positional
    results = fetch_results(lookback_days, token)          # <-- positional

    # --- build model ingredients ---
    ratings = build_ratings(results)                       # rolling team strengths
    elo_tbl = build_elo(results)                           # ELO ratings

    preds = []
    if not fixtures.empty:
        for _, row in fixtures.iterrows():
            home = str(row["home"])
            away = str(row["away"])
            utc = str(row["utc_date"])

            # components
            p_poiss = outcome_probs(home, away, ratings)
            p_elo = elo_match_probs(home, away, elo_tbl)

            # blend
            probs = {
                "home": blend_elo * p_elo["home"] + (1.0 - blend_elo) * p_poiss["home"],
                "draw": blend_elo * p_elo["draw"] + (1.0 - blend_elo) * p_poiss["draw"],
                "away": blend_elo * p_elo["away"] + (1.0 - blend_elo) * p_poiss["away"],
            }
            # ensure tidy rounding without changing totals too much
            probs = {k: round(float(v), 4) for k, v in probs.items()}

            # scorelines (poisson grid)
            scorelines = top_scorelines(home, away, ratings)

            # simple xG view from ratings
            xg = _expected_goals(ratings, home, away)

            preds.append(
                {
                    "match_id": f"{utc}_{_abbr(home)}-{_abbr(away)}",
                    "home": home,
                    "away": away,
                    "kickoff_utc": utc,
                    "xg": xg,
                    "probs": probs,
                    "probs_components": {
                        "poisson": {k: round(float(v), 4) for k, v in p_poiss.items()},
                        "elo": {k: round(float(v), 4) for k, v in p_elo.items()},
                    },
                    "scorelines_top": scorelines,
                    "notes": {"blend_elo": blend_elo},
                }
            )

    # --- write output JSON ---
    out = {"generated_utc": pd.Timestamp.utcnow().isoformat(), "predictions": preds}
    OUT_JSON.write_text(json.dumps(out, indent=2))
    print(f"[generate] wrote {OUT_JSON} with {len(preds)} predictions")


if __name__ == "__main__":
    main()
