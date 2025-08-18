# plpred/predict.py
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple


__all__ = [
    "outcome_probs",
    "top_scorelines",
    # helpers (kept internal but exported for completeness)
    "_as_float",
    "_pois",
    "_grid",
]


# ----------------------------
# Small, safe numeric helpers
# ----------------------------
def _as_float(x: Any, default: float | None = None) -> float:
    """Safely coerce to float; use `default` if it fails."""
    try:
        if x is None:
            raise ValueError
        return float(x)
    except Exception:
        if default is None:
            raise
        return float(default)


def _pois(lam: float, k: int) -> float:
    """Poisson PMF with guard rails."""
    lam = max(_as_float(lam, 0.0), 1e-9)
    k = int(k)
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _grid(mu_h: float, mu_a: float, cap: int = 10) -> List[List[float]]:
    """Independent goal grid up to `cap` for home/away Poisson means."""
    mu_h = _as_float(mu_h, 1.0)
    mu_a = _as_float(mu_a, 1.0)
    cap = int(cap)

    ph = [_pois(mu_h, i) for i in range(cap + 1)]
    pa = [_pois(mu_a, j) for j in range(cap + 1)]

    g = [[ph[i] * pa[j] for j in range(cap + 1)] for i in range(cap + 1)]

    # Normalise (finite cap truncation leaves a tiny remainder)
    s = sum(sum(row) for row in g)
    if s > 0:
        inv = 1.0 / s
        for i in range(cap + 1):
            for j in range(cap + 1):
                g[i][j] *= inv
    return g


# -----------------------------------------
# Public API used by both CI and Core flow
# -----------------------------------------
def outcome_probs(*args, **kwargs):
    """
    Dual-mode API (keeps CI happy and Core unchanged):

    1) **Numeric Poisson mode (tests)**:
       outcome_probs(mu_home, mu_away, draw_scale=1.0) -> (p_home, p_draw, p_away)

       - Returns a 3-tuple.
       - Optional draw_scale adjusts the draw probability before renormalisation.

    2) **Ratings-driven mode (Core)**:
       outcome_probs(home_team, away_team, ratings=<dict>) ->
           {"home": pH, "draw": pD, "away": pA, "mu_h": μH, "mu_a": μA}

       - `ratings` structure expected:
           {
             "teams": {
               "<Team>": {"att":..., "def":..., "att_h":..., "def_h":..., "att_a":..., "def_a":...},
               ...
             },
             "league_avg_gpg": 2.6,
             "home_adv": 1.10
           }
       - Falls back sensibly if keys are missing.
    """

    # ---- Numeric Poisson mode (CI tests) ----
    if len(args) >= 2 and all(isinstance(_as_float(a, None), float) for a in args[:2]):
        mu_h = _as_float(args[0])
        mu_a = _as_float(args[1])
        draw_scale = _as_float(kwargs.get("draw_scale", 1.0), 1.0)

        g = _grid(mu_h, mu_a, cap=int(kwargs.get("cap", 10)))

        # p(home win) = sum_{i>j} g[i][j]
        p_home = 0.0
        for i in range(1, len(g)):
            row = g[i]
            p_home += sum(row[:i])

        # p(away win) = sum_{j>i} g[i][j]
        p_away = 0.0
        for j in range(1, len(g)):
            col = sum(g[i][j] for i in range(j))
            p_away += col

        p_draw = 1.0 - p_home - p_away
        p_draw *= draw_scale
        # Renormalise after draw scaling
        norm = p_home + p_draw + p_away
        if norm > 0:
            p_home /= norm
            p_draw /= norm
            p_away /= norm
        return (p_home, p_draw, p_away)

    # ---- Ratings-driven mode (Core) ----
    if len(args) < 2:
        raise ValueError("outcome_probs requires (home, away, ...) in ratings mode")

    home = str(args[0])
    away = str(args[1])
    ratings: Dict[str, Any] = kwargs.get("ratings") or (args[2] if len(args) >= 3 else {})
    teams = ratings.get("teams", {}) or {}
    gpg = _as_float(ratings.get("league_avg_gpg", 2.6), 2.6)
    home_adv = _as_float(ratings.get("home_adv", 1.10), 1.10)

    def _get(team: str, key: str, fallback: float) -> float:
        return _as_float(teams.get(team, {}).get(key, fallback), fallback)

    # Fallback gracefully if split-home/away factors are missing
    att_h = _get(home, "att_h", _get(home, "att", 1.0))
    def_h = _get(home, "def_h", _get(home, "def", 1.0))
    att_a = _get(away, "att_a", _get(away, "att", 1.0))
    def_a = _get(away, "def_a", _get(away, "def", 1.0))

    mu_h = max(0.05, (gpg / 2.0) * att_h * def_a * home_adv)
    mu_a = max(0.05, (gpg / 2.0) * att_a * def_h)

    g = _grid(mu_h, mu_a, cap=int(kwargs.get("cap", 10)))

    p_home = 0.0
    for i in range(1, len(g)):
        p_home += sum(g[i][:i])

    p_away = 0.0
    for j in range(1, len(g)):
        p_away += sum(g[i][j] for i in range(j))

    p_draw = 1.0 - p_home - p_away

    return {"home": p_home, "draw": p_draw, "away": p_away, "mu_h": mu_h, "mu_a": mu_a}


def top_scorelines(mu_home: float, mu_away: float, *, k: int = 3, cap: int = 6) -> List[Dict[str, Any]]:
    """
    Return top-k most likely scorelines as:
      [{"home_goals": i, "away_goals": j, "prob": p}, ...]

    Accepts kwargs `k` and `cap` (CI tests pass k=3, cap=5).
    """
    mu_home = _as_float(mu_home, 1.0)
    mu_away = _as_float(mu_away, 1.0)
    cap = int(cap)
    k = max(1, int(k))

    g = _grid(mu_home, mu_away, cap=cap)

    flat: List[Tuple[float, int, int]] = []
    for i in range(cap + 1):
        for j in range(cap + 1):
            flat.append((g[i][j], i, j))
    flat.sort(reverse=True, key=lambda x: x[0])

    top = []
    for p, i, j in flat[:k]:
        top.append({"home_goals": i, "away_goals": j, "prob": p})
    return top
