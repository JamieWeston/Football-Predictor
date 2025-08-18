from __future__ import annotations
import math
from typing import Tuple, List, Dict

def _pois(k: int, lam: float) -> float:
    lam = max(lam, 1e-9)
    return math.exp(-lam) * (lam**k) / math.factorial(k)

def outcome_probs(lam: float, mu: float, draw_scale: float = 1.0, maxg: int = 8) -> Tuple[float,float,float]:
    ph = pd = pa = 0.0
    for i in range(maxg+1):
        pi = _pois(i, lam)
        for j in range(maxg+1):
            pj = _pois(j, mu)
            p = pi * pj
            if i>j: ph += p
            elif i==j: pd += p
            else: pa += p
    pd2 = max(min(pd * draw_scale, 0.95), 0.01)
    rest = max(ph + pa, 1e-12)
    scale = (1.0 - pd2) / rest
    return ph*scale, pd2, pa*scale

def top_scorelines(lam: float, mu: float, k: int = 3, cap: int = 5) -> List[Dict]:
    grid = []
    for i in range(cap):
        pi = _pois(i, lam)
        for j in range(cap):
            p = pi * _pois(j, mu)
            grid.append({"home_goals": i, "away_goals": j, "prob": round(p,4)})
    grid.sort(key=lambda x: x["prob"], reverse=True)
    return grid[:k]
