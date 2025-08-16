# scripts/model.py
import math
import numpy as np

def _poisson_vec(rate, max_goals):
    k = np.arange(max_goals + 1)
    pmf = np.exp(-rate) * np.power(rate, k) / np.maximum(1, np.array([np.math.factorial(int(i)) for i in k]))
    pmf /= pmf.sum()
    return pmf

class PoissonDC:
    """
    Poisson + Dixon–Coles model

    We map features to expected goals as:
      log(lambda_home) = log(base_home) + HA_club + attack_home - defence_away + adj
      log(mu_away)     = log(base_away) - HA_club + attack_away - defence_home + adj

    - attack/defence are log-strengths from rolling xG
    - HA_club is per-club (log) home advantage
    """
    def __init__(self, base_home=1.55, base_away=1.25, rho=-0.10, max_goals=10, floor_rate=0.12):
        self.base_home = float(base_home)
        self.base_away = float(base_away)
        self.rho = float(rho)
        self.max_goals = int(max_goals)
        self.floor_rate = float(floor_rate)

    def rates_from_features(self, atk_h, def_h, ha_h, atk_a, def_a, ha_a=0.0, extra_adj=0.0):
        log_lam = math.log(self.base_home) + ha_h + atk_h - def_a + extra_adj
        log_mu  = math.log(self.base_away) - ha_h + atk_a - def_h + extra_adj
        lam = max(self.floor_rate, float(math.exp(log_lam)))
        mu  = max(self.floor_rate, float(math.exp(log_mu)))
        return lam, mu

    def build_grid(self, lam, mu):
        ph = _poisson_vec(lam, self.max_goals)
        pa = _poisson_vec(mu,  self.max_goals)
        M = np.outer(ph, pa)

        # Dixon–Coles small-score adjustment
        rho = self.rho
        def f_adj(i, j):
            if i == 0 and j == 0: return 1.0 - lam * mu * rho
            if i == 0 and j == 1: return 1.0 + lam * rho
            if i == 1 and j == 0: return 1.0 + mu * rho
            if i == 1 and j == 1: return 1.0 - rho
            return 1.0

        for (i, j) in [(0,0), (0,1), (1,0), (1,1)]:
            M[i, j] *= max(0.0, f_adj(i, j))
        M /= M.sum()
        return M

    def probs_from_grid(self, M):
        idx = np.arange(M.shape[0])
        p_draw = float(M[idx, idx].sum())
        p_home = float(np.tril(M, -1).sum())
        p_away = float(np.triu(M, +1).sum())
        return p_home, p_draw, p_away

    def btts_over_under_from_grid(self, M, threshold=2.5):
        i = np.arange(M.shape[0]); j = np.arange(M.shape[1])
        I, J = np.meshgrid(i, j, indexing='ij')
        btts_yes = float(M[(I > 0) & (J > 0)].sum()); btts_no  = 1.0 - btts_yes
        over = float(M[(I + J) > threshold].sum());    under = 1.0 - over
        return btts_yes, btts_no, over, under

    def expected_goals_from_grid(self, M):
        i = np.arange(M.shape[0]); j = np.arange(M.shape[1])
        ex_h = float((M * i[:, None]).sum()); ex_a = float((M * j[None, :]).sum())
        return ex_h, ex_a

    def top_scorelines(self, M, k=3):
        items = []
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                items.append((float(M[i, j]), i, j))
        items.sort(reverse=True)
        return [{"home_goals": i, "away_goals": j, "prob": p} for p, i, j in items[:k]]

