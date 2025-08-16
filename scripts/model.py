# scripts/model.py
import math
import numpy as np

class PoissonDC:
    """
    Poisson score grid with a simple Dixon–Coles low-score adjustment.
    Provides helpers for 1X2/BTTS/O2.5, expected goals, and top-k scorelines.
    """

    def __init__(self, rho=-0.05, max_goals=6):
        self.rho = float(rho)
        self.max_goals = int(max_goals)

    def _independent_grid(self, lam, mu):
        # Independent Poisson(i;lam) * Poisson(j;mu)
        i = np.arange(0, self.max_goals + 1)
        j = np.arange(0, self.max_goals + 1)
        pi = np.exp(-lam) * (lam ** i) / np.maximum(1, np.array([math.factorial(k) for k in i]))
        pj = np.exp(-mu) * (mu ** j) / np.maximum(1, np.array([math.factorial(k) for k in j]))
        M = np.outer(pi, pj)
        return M

    def _dc_adjust(self, M):
        # Apply Dixon–Coles correlation on {0-0,1-0,0-1,1-1}, then renormalise
        M = M.copy()
        r = self.rho
        if r != 0.0:
            # Safe guard: tiny perturbations
            M[0,0] *= (1 + r)
            if M.shape[0] > 1 and M.shape[1] > 1:
                M[1,0] *= (1 - r)
                M[0,1] *= (1 - r)
                M[1,1] *= (1 + r)
        M /= M.sum()
        return M

    def build_grid(self, lam, mu):
        """Return (M, lam, mu) where M is (max_goals+1)x(max_goals+1) prob matrix."""
        lam = max(1e-6, float(lam))
        mu  = max(1e-6, float(mu))
        M = self._independent_grid(lam, mu)
        M = self._dc_adjust(M)
        return M, lam, mu

    # ---- Aggregates from grid ----
    def probs_from_grid(self, M):
        pH = float(np.tril(M, -1).sum())  # i>j
        pD = float(np.trace(M))
        pA = float(np.triu(M, 1).sum())   # j>i
        # numeric safety:
        s = pH + pD + pA
        if s > 0: pH, pD, pA = pH/s, pD/s, pA/s
        return pH, pD, pA

    def btts_over_under_from_grid(self, M):
        # BTTS Yes = sum of cells with i>0 and j>0
        i = np.arange(M.shape[0])
        j = np.arange(M.shape[1])
        I, J = np.meshgrid(i, j, indexing="ij")
        btts_yes = float(M[(I > 0) & (J > 0)].sum())
        btts_no  = 1.0 - btts_yes
        # Over/Under 2.5
        total = np.add.outer(i, j)
        over25 = float(M[total >= 3].sum())
        under25 = 1.0 - over25
        return btts_yes, btts_no, over25, under25

    def expected_goals_from_grid(self, M):
        i = np.arange(M.shape[0])
        j = np.arange(M.shape[1])
        ex_h = float((M * i.reshape(-1,1)).sum())
        ex_a = float((M * j.reshape(1,-1)).sum())
        return ex_h, ex_a

    def top_k_scores(self, M, k=3):
        out = []
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                out.append((f"{i}-{j}", float(M[i, j])))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:k]
