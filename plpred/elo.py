from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Dict, Any
import pandas as pd

DEFAULT_INIT = 1500.0
DEFAULT_SCALE = 400.0
DEFAULT_K = 20.0
DEFAULT_HA_POINTS = 60.0

def _parse_date(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception:
        return datetime.now(timezone.utc)

def _half_life_weight(age_days: float, half_life_days: float) -> float:
    if half_life_days <= 0: return 1.0
    return 0.5 ** (age_days / half_life_days)

def _expected_Elo(delta_points: float, scale: float = DEFAULT_SCALE) -> float:
    return 1.0 / (1.0 + 10.0 ** (-delta_points / scale))

def _goal_diff_factor(gd: int, delta_abs: float) -> float:
    gd = abs(int(gd))
    if gd <= 1:
        G = 1.0
    elif gd == 2:
        G = 1.5
    else:
        G = (11.0 + gd) / 8.0
    return G * (2.2 / (0.001 * delta_abs + 2.2))

def build_elo(df: pd.DataFrame,
              init: float = DEFAULT_INIT,
              k_base: float = DEFAULT_K,
              scale: float = DEFAULT_SCALE,
              half_life_days: float = 365.0,
              home_adv_points: float = DEFAULT_HA_POINTS) -> Dict[str, Any]:
    if df.empty:
        return {"init": init, "scale": scale, "k_base": k_base,
                "home_adv_points": home_adv_points, "draw_nu": 1.0, "teams": {}}

    df = df.copy()
    df["kick_dt"] = df["utc_date"].apply(_parse_date)
    df = df.sort_values("kick_dt").reset_index(drop=True)

    draws = (df["home_goals"] == df["away_goals"]).sum()
    draw_rate = draws / max(len(df), 1)
    draw_rate = min(max(float(draw_rate), 0.15), 0.35)
    draw_nu = (2.0 * draw_rate) / max(1.0 - draw_rate, 1e-6)

    ratings: Dict[str, float] = {}
    games_count: Dict[str, int] = {}

    now = datetime.now(timezone.utc)
    for _, m in df.iterrows():
        h = m["home"]; a = m["away"]
        hg = int(m["home_goals"]); ag = int(m["away_goals"])
        dt = m["kick_dt"]
        age_days = (now - dt).total_seconds()/86400.0
        w_time = _half_life_weight(age_days, half_life_days)

        Rh = ratings.get(h, init)
        Ra = ratings.get(a, init)
        delta = (Rh + home_adv_points) - Ra
        Eh = _expected_Elo(delta, scale=scale)

        if hg > ag:
            Sh = 1.0
        elif hg == ag:
            Sh = 0.5
        else:
            Sh = 0.0

        gd = abs(hg - ag)
        g = _goal_diff_factor(gd, abs(delta))
        K = k_base * w_time

        change = K * g * (Sh - Eh)
        ratings[h] = Rh + change
        ratings[a] = Ra - change
        games_count[h] = games_count.get(h, 0) + 1
        games_count[a] = games_count.get(a, 0) + 1

    teams = {t: {"elo": float(ratings[t]), "games": int(games_count.get(t,0))}
             for t in ratings.keys()}

    return {
        "init": float(init),
        "scale": float(scale),
        "k_base": float(k_base),
        "home_adv_points": float(home_adv_points),
        "draw_nu": float(draw_nu),
        "teams": teams
    }

def elo_match_probs(elo_h: float, elo_a: float,
                    home_adv_points: float,
                    scale: float,
                    draw_nu: float) -> tuple[float,float,float]:
    delta = (elo_h + home_adv_points) - elo_a
    r = 10.0 ** (delta / max(scale, 1e-6))
    r_sqrt = math.sqrt(r)
    denom = r + 1.0 + draw_nu * r_sqrt
    if denom <= 0:
        return 1/3, 1/3, 1/3
    pH = r / denom
    pD = (draw_nu * r_sqrt) / denom
    pA = 1.0 / denom
    s = pH + pD + pA
    if s <= 0: return 1/3,1/3,1/3
    return pH/s, pD/s, pA/s
