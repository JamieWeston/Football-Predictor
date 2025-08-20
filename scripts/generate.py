# scripts/generate.py
from __future__ import annotations

import os
import json
import datetime as _dt
from pathlib import Path
from typing import Dict, Any, List, Tuple
from collections import Counter

import pandas as pd

from plpred.fd_client import fetch_fixtures  # your client
from plpred.predict import (
    expected_goals_for_pair,
    outcome_probs,
    top_scorelines,
)

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

DEBUG_PATH = REPORTS_DIR / "fixtures_fetch_debug.json"


def _read_json(p: Path) -> Any:
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _write_json(p: Path, obj: Any) -> None:
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def load_ratings() -> Dict[str, Any]:
    # try preferred first
    for candidate in [
        DATA_DIR / "team_ratings.json",
        DATA_DIR / "team_strengths.json",
    ]:
        obj = _read_json(candidate)
        if obj:
            print(f"[gen] loaded ratings from {candidate}")
            return obj
    print("[gen] WARNING: no ratings found; using neutral baselines.")
    return {
        "base_home_xg": 1.45,
        "base_away_xg": 1.35,
        "draw_scale": 1.0,
        "teams": {}
    }


# ---------------------------
# Fixture fetching (robust)
# ---------------------------

def _is_fd_matches_payload(x: Any) -> bool:
    """Return True if `x` looks like the raw FD payload: {'matches': [...] }."""
    return isinstance(x, dict) and "matches" in x and isinstance(x["matches"], list)


def _normalise_fd_matches_payload(x: Dict[str, Any]) -> pd.DataFrame:
    """Convert raw FD 'matches' payload to our columns."""
    rows = []
    for m in x.get("matches", []):
        rows.append({
            "match_id": m.get("id") or None,
            "utc_date": m.get("utcDate"),
            "home": (m.get("homeTeam") or {}).get("name"),
            "away": (m.get("awayTeam") or {}).get("name"),
            "competition": (m.get("competition") or {}).get("code") or (m.get("competition") or {}).get("name"),
            "status": m.get("status"),
        })
    df = pd.DataFrame(rows)
    return df


def _ensure_df(obj: Any) -> pd.DataFrame:
    """Accept list/df/raw-FD and produce a DF with our required columns if possible."""
    if isinstance(obj, pd.DataFrame):
        return obj.copy()

    if isinstance(obj, list):
        return pd.DataFrame(obj)

    if _is_fd_matches_payload(obj):
        return _normalise_fd_matches_payload(obj)

    # object with 'matches' nested under another key (rare)
    if isinstance(obj, dict):
        for v in obj.values():
            if _is_fd_matches_payload(v):
                return _normalise_fd_matches_payload(v)

    # Nothing usable
    return pd.DataFrame()


def _finalise_fixtures_df(df: pd.DataFrame, label: str) -> pd.DataFrame:
    # Rename common alt names -> canonical
    rename_map = {
        "utcDate": "utc_date",
        "homeTeam": "home",
        "awayTeam": "away",
    }
    df = df.rename(columns=rename_map)

    need = ["utc_date", "home", "away"]
    # If home/away columns are objects with {'name': ..}, pull name
    for col in ["home", "away"]:
        if col in df.columns and df[col].apply(lambda x: isinstance(x, dict) and "name" in x).any():
            df[col] = df[col].apply(lambda x: x.get("name") if isinstance(x, dict) else x)

    # ensure required columns
    missing = [c for c in need if c not in df.columns]
    if missing:
        print(f"[gen] [{label}] fixtures missing columns {missing} -> discarding")
        return pd.DataFrame(columns=["match_id", "utc_date", "home", "away"])

    # Create match_id if not present
    if "match_id" not in df.columns or df["match_id"].isna().all():
        df["match_id"] = [
            f"{r['utc_date']}_{(r['home'] or '')[:3]}-{(r['away'] or '')[:3]}"
            for r in df.to_dict("records")
        ]

    # Ensure utc_date strings
    df["utc_date"] = df["utc_date"].astype(str)
    df["home"] = df["home"].astype(str)
    df["away"] = df["away"].astype(str)

    # Keep only future fixtures or today onwards
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    df = df[df["utc_date"] >= today].reset_index(drop=True)
    return df[["match_id", "utc_date", "home", "away"]]


def fetch_fixtures_robust(days: int = 21) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Try several strategies, then fall back to local data/fixtures.json.
    Returns (df, debug_dict)
    """
    dbg = {"attempts": []}
    token = os.getenv("FOOTBALL_DATA_TOKEN")

    # A) modern rolling window
    try:
        obj = fetch_fixtures(days=days, token=token)
        df = _finalise_fixtures_df(_ensure_df(obj), "modern")
        dbg["attempts"].append({"strategy": "modern", "rows": len(df)})
        if not df.empty:
            return df, dbg
    except Exception as e:
        dbg["attempts"].append({"strategy": "modern", "error": repr(e)})

    # B) legacy (league window)
    try:
        today = _dt.date.today()
        date_from = today.isoformat()
        date_to = (today + _dt.timedelta(days=days)).isoformat()
        obj = fetch_fixtures(None, "PL", date_from, date_to)  # legacy signature
        df = _finalise_fixtures_df(_ensure_df(obj), "legacy-league")
        dbg["attempts"].append({"strategy": "legacy-league", "rows": len(df)})
        if not df.empty:
            return df, dbg
    except Exception as e:
        dbg["attempts"].append({"strategy": "legacy-league", "error": repr(e)})

    # C) fallback to local data/fixtures.json (if present)
    try:
        local = _read_json(DATA_DIR / "fixtures.json") or []
        df = _finalise_fixtures_df(_ensure_df(local), "local-file")
        dbg["attempts"].append({"strategy": "local-file", "rows": len(df)})
        if not df.empty:
            return df, dbg
    except Exception as e:
        dbg["attempts"].append({"strategy": "local-file", "error": repr(e)})

    # give up (empty)
    return pd.DataFrame(columns=["match_id", "utc_date", "home", "away"]), dbg


# ---------------------------
# Predictions
# ---------------------------

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

    # quick diagnostics for mapping quality
    _write_json(REPORTS_DIR / "name_resolution.json", {
        "counts": {f"{k[0]}|{k[1]}": v for k, v in resolve_counts.items()},
        "examples": debug_rows[:100],
    })

    return out


def main() -> None:
    ratings = load_ratings()

    # window (default 21) can be overridden from workflow env
    window_days = int(os.getenv("FD_WINDOW_DAYS", "21"))
    fixtures_df, dbg = fetch_fixtures_robust(days=window_days)

    # persist diagnostics
    _write_json(DEBUG_PATH, dbg)

    if fixtures_df.empty:
        print("[gen] No fixtures found after all strategies. Writing empty predictions.json")
        _write_json(DATA_DIR / "predictions.json", {
            "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "predictions": []
        })
        return

    # Always save what we used (helps debugging + offers future local fallback)
    _write_json(DATA_DIR / "fixtures.json", fixtures_df.to_dict("records"))

    preds_obj = build_predictions(fixtures_df, ratings)
    _write_json(DATA_DIR / "predictions.json", preds_obj)

    print(f"[gen] Fixtures used: {len(fixtures_df)}")
    print(f"[gen] Wrote: data/predictions.json, data/fixtures.json, "
          f"reports/name_resolution.json, {DEBUG_PATH}")


if __name__ == "__main__":
    main()
