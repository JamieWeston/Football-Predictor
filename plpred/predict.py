# plpred/predict.py
from __future__ import annotations

import math
from typing import Dict, Tuple, List


def _as_float(x, default: float = 1.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _pois(k: int, lam: float) -> float:
    lam = _as_float(lam, 0.0)
    lam = max(lam, 1e-12)
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _grid_probs(mu_h: float, mu_a: float, limit: int = 10) -> List[List[float]]:
    """Independent Poisson grid (home rows, away columns)."""
    mu_h = _as_float(mu_h)
    mu_a = _as_float(mu_a)
    grid = [[_pois(i, mu_h) * _pois(j, mu_a) for j in range(limit + 1)] for i in range(limit + 1)]
    # Renormalize for the truncation
    s = sum(sum(r) for r in grid)
    if s > 0:
        inv = 1.0 / s
        for i in range(limit + 1):
            for j in range(limit + 1):
                grid[i][j] *= inv
    return grid


def outcome_probs(home: str, away: str, ratings: Dict) -> Dict[str, float]:
    """
    Compute 1X2 probabilities from ratings dict.
    ratings must have:
      ratings["teams"][team]["att"], ["def"], optionally ["att_h"], ["def_h"], ["att_a"], ["def_a"]
      ratings["league_avg_gpg"], ratings["home_adv"]
    Falls back to neutral values if a team is missing.
    """
    teams = ratings.get("teams", {})
    gpg = _as_float(ratings.get("league_avg_gpg", 2.6))
    home_adv = _as_float(ratings.get("home_adv", 1.10))

    def _get(team: str, key: str, fallback: float) -> float:
        return _as_float(teams.get(team, {}).get(key, fallback), fallback)

    # use team-specific H/A if present, else global att/def
    att_h = _get(home, "att_h", _get(home, "att", 1.0))
    def_h = _get(home, "def_h", _get(home, "def", 1.0))
    att_a = _get(away, "att_a", _get(away, "att", 1.0))
    def_a = _get(away, "def_a", _get(away, "def", 1.0))

    mu_h = max(0.05, (gpg / 2.0) * att_h * def_a * home_adv)
    mu_a = max(0.05, (gpg / 2.0) * att_a * def_h)

    grid = _grid_probs(mu_h, mu_a)
    p_home = sum(sum(row[j] for j in range(i)) for i, row in enumerate(grid[1:], start=1))
    p_away = sum(sum(grid[i][j] for i in range(j)) for j in range(1, len(grid)))
    p_draw = 1.0 - p_home - p_away

    return {"home": p_home, "draw": p_draw, "away": p_away, "mu_h": mu_h, "mu_a": mu_a}


def top_scorelines(mu_h: float, mu_a: float, n: int = 3) -> List[Dict]:
    grid = _grid_probs(mu_h, mu_a)
    cells = []
    for i in range(len(grid)):
        for j in range(len(grid)):
            cells.append((grid[i][j], i, j))
    cells.sort(reverse=True)
    out = []
    for p, i, j in cells[:n]:
        out.append({"home_goals": i, "away_goals": j, "prob": round(p, 4)})
    return out
