# plpred/predict.py
from __future__ import annotations

import math
from typing import Dict, List, Any


def _as_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _pois(k: int, lam: float) -> float:
    lam = max(_as_float(lam, 0.0), 1e-12)
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _grid(mu_h: float, mu_a: float, limit: int = 10) -> List[List[float]]:
    grid = [[_pois(i, mu_h) * _pois(j, mu_a) for j in range(limit + 1)]
            for i in range(limit + 1)]
    s = sum(sum(r) for r in grid)
    if s > 0:
        inv = 1.0 / s
        for i in range(limit + 1):
            for j in range(limit + 1):
                grid[i][j] *= inv
    return grid


def outcome_probs(*args, **kwargs) -> Dict[str, float]:
    """
    Back-compat and modern:

    - Old tests: outcome_probs(mu_h: float, mu_a: float, draw_scale=1.0)
    - Modern:    outcome_probs(home: str, away: str, ratings: dict)

    Returns dict with keys: home, draw, away (+ mu_h, mu_a)
    """
    # Poisson-only mode (tests)
    if len(args) >= 2 and all(isinstance(_as_float(a, None), float) for a in args[:2]):
        mu_h = _as_float(args[0]); mu_a = _as_float(args[1])
        draw_scale = _as_float(kwargs.get("draw_scale", 1.0), 1.0)
        g = _grid(mu_h, mu_a)
        p_home = sum(sum(row[j] for j in range(i)) for i, row in enumerate(g[1:], start=1))
        p_away = sum(sum(g[i][j] for i in range(j)) for j in range(1, len(g)))
        p_draw = 1.0 - p_home - p_away
        # optional draw scaling (renormalize)
        p_draw *= draw_scale
        norm = p_home + p_away + p_draw
        if norm > 0:
            p_home /= norm; p_away /= norm; p_draw /= norm
        return {"home": p_home, "draw": p_draw, "away": p_away, "mu_h": mu_h, "mu_a": mu_a}

    # Ratings-mode (runtime)
    home, away = str(args[0]), str(args[1])
    ratings: Dict[str, Any] = kwargs.get("ratings") or (args[2] if len(args) >= 3 else {})
    teams = ratings.get("teams", {})
    gpg = _as_float(ratings.get("league_avg_gpg", 2.6), 2.6)
    home_adv = _as_float(ratings.get("home_adv", 1.10), 1.10)

    def _get(team: str, key: str, fallback: float) -> float:
        return _as_float(teams.get(team, {}).get(key, fallback), fallback)

    att_h = _get(home, "att_h", _get(home, "att", 1.0))
    def_h = _get(home, "def_h", _get(home, "def", 1.0))
    att_a = _get(away, "att_a", _get(away, "att", 1.0))
    def_a = _get(away, "def_a", _get(away, "def", 1.0))

    mu_h = max(0.05, (gpg / 2.0) * att_h * def_a * home_adv)
    mu_a = max(0.05, (gpg / 2.0) * att_a * def_h)

    g = _grid(mu_h, mu_a)
    p_home = sum(sum(row[j] for j in range(i)) for i, row in enumerate(g[1:], start=1))
    p_away = sum(sum(g[i][j] for i in range(j)) for j in range(1, len(g)))
    p_draw = 1.0 - p_home - p_away
    return {"home": p_home, "draw": p_draw, "away": p_away, "mu_h": mu_h, "mu_a": mu_a}


def top_scorelines(mu_h: float, mu_a: float, n: int = 3, **kwargs) -> List[Dict]:
    """Back-compat: accept k=..., cap=... aliases."""
    if "k" in kwargs:
        n = int(kwargs["k"])
    limit = int(kwargs.get("cap", 10))
    g = _grid(_as_float(mu_h), _as_float(mu_a), limit=limit)
    cells = []
    for i in range(len(g)):
        for j in range(len(g)):
            cells.append((g[i][j], i, j))
    cells.sort(reverse=True)
    out = [{"home_goals": i, "away_goals": j, "prob": round(p, 4)}
           for p, i, j in cells[:n]]
    return out
