import math, numpy as np
from typing import Tuple

class PoissonDC:
    def __init__(self, base_home_goals=1.50, base_away_goals=1.30, alpha_strength=0.35, home_adv_log=0.06, rho_dc=0.06, max_goals=6):
        self.base_home_goals = base_home_goals
        self.base_away_goals = base_away_goals
        self.alpha_strength = alpha_strength
        self.home_adv_log = home_adv_log
        self.rho_dc = rho_dc
        self.max_goals = max_goals

    @staticmethod
    def _pois(k, lam):
        return math.exp(-lam) * lam**k / math.factorial(k)

    def _dc_adj(self, i, j):
        rho = self.rho_dc
        if i==0 and j==0: return 1 - rho
        if i==1 and j==0: return 1 + rho
        if i==0 and j==1: return 1 + rho
        if i==1 and j==1: return 1 - rho
        return 1.0

    def build_grid(self, r_home: float, r_away: float) -> Tuple[np.ndarray, float, float]:
        # ratings are z-scores; convert to lambda & mu
        diff = self.alpha_strength * (r_home - r_away)
        lam = self.base_home_goals * math.exp(diff + self.home_adv_log)
        mu  = self.base_away_goals * math.exp(-diff)
        M = np.zeros((self.max_goals+1, self.max_goals+1))
        for i in range(self.max_goals+1):
            for j in range(self.max_goals+1):
                M[i,j] = self._pois(i, lam) * self._pois(j, mu) * self._dc_adj(i,j)
        M = M / M.sum()
        return M, lam, mu

    @staticmethod
    def probs_from_grid(M: np.ndarray):
        p_home = sum(M[i, :i].sum() for i in range(M.shape[0]))
        p_draw = np.trace(M)
        p_away = 1 - p_home - p_draw
        return float(p_home), float(p_draw), float(p_away)

    @staticmethod
    def btts_over_under_from_grid(M: np.ndarray):
        maxg = M.shape[0]-1
        btts_yes = sum(M[i,j] for i in range(1,maxg+1) for j in range(1,maxg+1))
        over25 = sum(M[i,j] for i in range(maxg+1) for j in range(maxg+1) if i+j>=3)
        return float(btts_yes), float(1-btts_yes), float(over25), float(1-over25)

    @staticmethod
    def expected_goals_from_grid(M: np.ndarray):
        maxg = M.shape[0]-1
        ex_h = sum(i * M[i,:].sum() for i in range(maxg+1))
        ex_a = sum(j * M[:,j].sum() for j in range(maxg+1))
        return float(ex_h), float(ex_a)
