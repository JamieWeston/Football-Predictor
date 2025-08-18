# scripts/model.py
import math
import numpy as np

MAX_GOALS = 10  # grid

def poisson_grid(lam: float, mu: float):
    """Return independent Poisson goal grid Px[i,j] for i,j=0..MAX_GOALS."""
    i = np.arange(MAX_GOALS + 1)
    j = np.arange(MAX_GOALS + 1)
    p_home = np.exp(-lam) * np.power(lam, i) / np.vectorize(math.factorial)(i)
    p_away = np.exp(-mu) * np.power(mu, j) / np.vectorize(math.factorial)(j)
    return np.outer(p_home, p_away)

def dixon_coles_adjust(P: np.ndarray, lam: float, mu: float, rho: float = -0.13):
    """
    Apply DC adjustment to low-score cells. rho<0 typically increases 0-0 and 1-1 a bit.
    """
    P = P.copy()
    # probabilities for 0-0, 0-1, 1-0, 1-1:
    p00 = math.exp(-(lam + mu))
    p01 = math.exp(-(lam + mu)) * mu
    p10 = math.exp(-(lam + mu)) * lam
    p11 = math.exp(-(lam + mu)) * lam * mu

    # Apply scaling factor to these four cells only
    P[0, 0] *= (1 + rho)
    if MAX_GOALS >= 1:
        P[0, 1] *= (1 - rho)
        P[1, 0] *= (1 - rho)
        P[1, 1] *= (1 + rho)

    # renormalize
    P /= P.sum()
    return P

def markets_from_grid(P: np.ndarray):
    i = np.arange(P.shape[0])
    j = np.arange(P.shape[1])
    I, J = np.meshgrid(i, j, indexing="ij")

    home = float(P[I > J].sum())
    draw = float(P[I == J].sum())
    away = float(P[I < J].sum())

    btts_yes = float(P[(I > 0) & (J > 0)].sum())
    btts_no = 1.0 - btts_yes

    over25 = float(P[(I + J) >= 3].sum())
    under25 = 1.0 - over25

    # top 3 scorelines
    flat = []
    for hi in range(P.shape[0]):
        for aj in range(P.shape[1]):
            flat.append((hi, aj, float(P[hi, aj])))
    flat.sort(key=lambda x: x[2], reverse=True)
    top3 = [{"home_goals": a, "away_goals": b, "prob": p} for a, b, p in flat[:3]]

    return {
        "probs": {"home": home, "draw": draw, "away": away},
        "btts": {"yes": btts_yes, "no": btts_no},
        "totals_2_5": {"over": over25, "under": under25},
        "scorelines_top": top3,
    }
