# scripts/generate.py
# CORE generator with on-the-fly ratings + ELO and robust name normalisation.
# - If data/team_strengths.json or ELO isn't available, build from recent FD results.
# - Blends Poisson (from ratings) with ELO probabilities.
# - Emits detailed notes to help diagnose fallbacks.

from __future__ import annotations
import os
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Tuple

import pandas as pd

from plpred.fd_client import fetch_fixtures, fetch_results
from plpred.ratings import build_ratings
from plpred.elo import build_elo, elo_match_probs
from plpred.predict import outcome_probs, top_scorelines

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------- helpers ----------

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _norm_team(name: str) -> str:
    """Normalise team text so fixtures and results can be joined reliably."""
    if not isinstance(name, str):
        return name
    n = name
    n = n.replace("&", "and")
    n = n.replace(".", " ")
    n = n.replace("  ", " ")
    # strip trailing competition artifacts
    n = n.strip()
    # drop trailing "FC" / "AFC" / "CF" / "SC" tokens
    tokens = [t for t in n.split() if t.upper() not in {"FC", "AFC", "CF", "SC"}]
    n = " ".join(tokens)
    # common tidy-ups
    n = n.replace(" Utd", " United")
    n = n.replace(" Hotspur", " Hotspur")
    # fold repeated whitespace
    n = " ".join(n.split())
    return n

def _split_home_away_from_avg(league_avg_gpg: float, home_share: float = 0.58) -> Tuple[float, float]:
    """Split league average goals into home/away means (roughly EPL-ish)."""
    home = max(0.6, league_avg_gpg * home_share)
    away = max(0.5, league_avg_gpg * (1.0 - home_share))
    return home, away

def _load_json(path: Path) -> Any | None:
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def _write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    tmp.replace(path)

# ---------- main core pipeline ----------

def main() -> int:
    os.environ.setdefault("PYTHONHASHSEED", "0")
    window_days = int(os.getenv("FD_WINDOW_DAYS", "21"))
    blend_elo = float(os.getenv("BLEND_ELO", "0.35"))  # 0..1
    token = os.getenv("FOOTBALL_DATA_TOKEN", "")

    # 1) fixtures (next N days)
    fixtures = fetch_fixtures(days_ahead=window_days, token=token)
    if fixtures.empty:
        out = {"generated_utc": _now_utc_iso(), "predictions": [], "notes": {"reason": "no-fixtures"}}
        _write_json(DATA_DIR / "predictions.json", out)
        print("[core] no fixtures. wrote empty predictions.json")
        return 0

    # 2) ensure normalised fixture names
    fixtures = fixtures.copy()
    fixtures["home_n"] = fixtures["home"].map(_norm_team)
    fixtures["away_n"] = fixtures["away"].map(_norm_team)

    # 3) Load or build ratings from recent FD results
    ratings_path = DATA_DIR / "team_strengths.json"
    ratings = _load_json(ratings_path)

    # if ratings missing/invalid, build them now
    build_reason = None
    if not ratings or "teams" not in ratings or not isinstance(ratings["teams"], dict):
        days_back = int(os.getenv("FD_RESULTS_LOOKBACK_DAYS", "400"))
        results = fetch_results(days_back=days_back, token=token)
        if results.empty:
            print("[warn] could not fetch results; strengths will be neutral.")
            ratings = {"teams": {}, "league_avg_gpg": 2.6, "home_adv": 1.08}
            build_reason = "neutral"
        else:
            # normalise so names align with fixtures
            results = results.copy()
            results["home"] = results["home"].map(_norm_team)
            results["away"] = results["away"].map(_norm_team)
            ratings = build_ratings(results)
            build_reason = "built_from_fd"
            try:
                _write_json(ratings_path, ratings)
            except Exception as e:
                print(f"[warn] could not write {ratings_path}: {e}")

    # 4) Load or build ELO from the same results (if not already created)
    elo_path = DATA_DIR / "elo.json"
    elo = _load_json(elo_path)
    if not elo or not isinstance(elo, dict) or "ratings" not in elo:
        days_back = int(os.getenv("FD_RESULTS_LOOKBACK_DAYS", "400"))
        res_for_elo = fetch_results(days_back=days_back, token=token)
        if res_for_elo.empty:
            print("[warn] could not fetch results for ELO; will use neutral ELO=1500.")
            elo = {"ratings": {}}
        else:
            res_for_elo = res_for_elo.copy()
            res_for_elo["home"] = res_for_elo["home"].map(_norm_team)
            res_for_elo["away"] = res_for_elo["away"].map(_norm_team)
            elo = build_elo(res_for_elo)
            try:
                _write_json(elo_path, elo)
            except Exception as e:
                print(f"[warn] could not write {elo_path}: {e}")

    teams = ratings.get("teams", {})
    avg_gpg = float(ratings.get("league_avg_gpg", 2.6))
    home_adv = float(ratings.get("home_adv", 1.08))
    base_home, base_away = _split_home_away_from_avg(avg_gpg, home_share=0.58)

    NEUTRAL = {"att": 1.0, "def": 1.0, "att_h": 1.0, "def_h": 1.0, "att_a": 1.0, "def_a": 1.0}

    preds = []
    missing_teams = set()

    for _, row in fixtures.iterrows():
        h_raw, a_raw = row["home"], row["away"]
        h, a = row["home_n"], row["away_n"]
        kickoff = row["utc_date"]

        th = teams.get(h, NEUTRAL)
        ta = teams.get(a, NEUTRAL)
        if th is NEUTRAL:
            missing_teams.add(h_raw)
        if ta is NEUTRAL:
            missing_teams.add(a_raw)

        # λ/μ from team strengths
        lam = base_home * th.get("att_h", 1.0) * ta.get("def_a", 1.0) * home_adv
        mu = base_away * ta.get("att_a", 1.0) * th.get("def_h", 1.0)

        # guard rails
        lam = max(0.05, float(lam))
        mu = max(0.05, float(mu))

        # Poisson probabilities
        p_home_pois, p_draw_pois, p_away_pois = outcome_probs(lam, mu)

        # ELO probabilities (falls back to neutral if a rating missing)
        try:
            p_home_elo, p_draw_elo, p_away_elo = elo_match_probs(elo, h, a)
        except Exception:
            p_home_elo, p_draw_elo, p_away_elo = 0.3923, 0.33, 0.2777

        w = float(blend_elo)
        p_home = (1 - w) * p_home_pois + w * p_home_elo
        p_draw = (1 - w) * p_draw_pois + w * p_draw_elo
        p_away = (1 - w) * p_away_pois + w * p_away_elo

        # normalise just in case of numeric drift
        s = p_home + p_draw + p_away
        if s > 0:
            p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s

        scorelines = top_scorelines(lam, mu, k=3)

        # tiny-rates warning (helps catch future issues)
        if lam + mu < 0.35:
            print(f"[warn] very small rates {h_raw} vs {a_raw}: lam={lam:.2f}, mu={mu:.2f}")

        preds.append({
            "match_id": f"{kickoff}_{h[:3]}-{a[:3]}",
            "home": h_raw,
            "away": a_raw,
            "kickoff_utc": kickoff,
            "xg": {"home": round(lam, 2), "away": round(mu, 2)},
            "probs": {"home": round(p_home, 4), "draw": round(p_draw, 4), "away": round(p_away, 4)},
            "probs_components": {
                "poisson": {
                    "home": round(p_home_pois, 4),
                    "draw": round(p_draw_pois, 4),
                    "away": round(p_away_pois, 4),
                },
                "elo": {
                    "home": round(p_home_elo, 4),
                    "draw": round(p_draw_elo, 4),
                    "away": round(p_away_elo, 4),
                },
            },
            "scorelines_top": [
                {"home_goals": int(s["home_goals"]), "away_goals": int(s["away_goals"]), "prob": round(float(s["prob"]), 4)}
                for s in scorelines
            ],
            "notes": {"blend_elo": w}
        })

    out = {
        "generated_utc": _now_utc_iso(),
        "predictions": preds,
        "notes": {
            "ratings_source": "cache" if build_reason is None else build_reason,
            "teams_missing_strengths": sorted(list(missing_teams))[:10],  # sample first 10 for brevity
            "avg_gpg": avg_gpg,
            "home_adv": home_adv,
        }
    }
    _write_json(DATA_DIR / "predictions.json", out)
    print(f"[core] wrote {len(preds)} predictions to data/predictions.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
