# scripts/model.py
import math
import numpy as np

def _poisson_vec(rate, max_goals):
    """Poisson PMF vector for k=0..max_goals."""
    k = np.arange(max_goals + 1)
    # use log-Poisson for numerical stability
    # P(k)=exp(-rate)*rate^k/k!
    # np.exp(k*np.log(rate) - rate - gammaln(k+1)) also works
    pmf = np.exp(-rate) * np.power(rate, k) / np.maximum(1, np.array([math.factorial(int(i)) for i in k]))
    pmf /= pmf.sum()
    return pmf

class PoissonDC:
    """
    Poisson + Dixon–Coles with a safe mapping from ratings -> goal rates.

    - base_home / base_away: league-average expected goals for home/away teams
      when ratings are equal (or unknown).
    - k: how strongly rating difference shifts the rates (log-link).
    - rho: Dixon–Coles small-score correlation adjustment.
    - floor_rate: minimum lambda/mu to avoid 0.0 grids.
    """
    def __init__(
        self,
        base_home=1.55,
        base_away=1.25,
        k=0.25,
        rho=-0.10,
        max_goals=10,
        floor_rate=0.12
    ):
        self.base_home = float(base_home)
        self.base_away = float(base_away)
        self.k = float(k)
        self.rho = float(rho)
        self.max_goals = int(max_goals)
        self.floor_rate = float(floor_rate)

    def rates(self, r_home: float, r_away: float):
        """
        Map (rating_home, rating_away) -> (lambda_home, mu_away) safely.

        We use a log-link so that equal ratings give the base rates, and
        differences tilt them. We also clamp to a small positive floor.
        """
        diff = (r_home or 0.0) - (r_away or 0.0)
        lam = self.base_home * math.exp(self.k * diff)
        mu  = self.base_away * math.exp(-self.k * diff)  # mirror

        # Protect against zeros / negatives
        lam = max(self.floor_rate, float(lam))
        mu  = max(self.floor_rate, float(mu))
        return lam, mu

    def build_grid(self, r_home: float, r_away: float):
        """
        Build the scoreline probability grid with DC small-score adjustment.
        Returns (M, lam, mu), where M[i,j] = P(home=i, away=j).
        """
        lam, mu = self.rates(r_home, r_away)

        ph = _poisson_vec(lam, self.max_goals)  # home goals pmf
        pa = _poisson_vec(mu,  self.max_goals)  # away goals pmf

        M = np.outer(ph, pa)  # independent Poisson grid

        # Dixon–Coles adjustment for small scores
        rho = self.rho
        # adjust only a few cells (0-0, 0-1, 1-0, 1-1)
        def f_adj(i, j):
            if i == 0 and j == 0:
                return 1.0 - lam * mu * rho
            if i == 0 and j == 1:
                return 1.0 + lam * rho
            if i == 1 and j == 0:
                return 1.0 + mu * rho
            if i == 1 and j == 1:
                return 1.0 - rho
            return 1.0

        # apply and renormalize
        for (i, j) in [(0,0), (0,1), (1,0), (1,1)]:
            if i <= self.max_goals and j <= self.max_goals:
                M[i, j] *= max(0.0, f_adj(i, j))

        M_sum = M.sum()
        if M_sum <= 0:
            # fallback if something went numerically wrong
            M = np.outer(ph, pa)
            M_sum = M.sum()
        M /= M_sum

        return M, lam, mu

    def probs_from_grid(self, M: np.ndarray):
        """Return (p_home, p_draw, p_away)."""
        idx = np.arange(M.shape[0])
        p_draw = float(M[idx, idx].sum())
        # home wins: i > j
        p_home = float(np.tril(M, -1).sum())
        # away wins: i < j
        p_away = float(np.triu(M, +1).sum())
        return p_home, p_draw, p_away

    def btts_over_under_from_grid(self, M: np.ndarray, threshold=2.5):
        i = np.arange(M.shape[0])
        j = np.arange(M.shape[1])
        I, J = np.meshgrid(i, j, indexing='ij')

        btts_yes = float(M[(I > 0) & (J > 0)].sum())
        btts_no  = 1.0 - btts_yes

        over = float(M[(I + J) > threshold].sum())
        under = 1.0 - over
        return btts_yes, btts_no, over, under

    def expected_goals_from_grid(self, M: np.ndarray):
        i = np.arange(M.shape[0])
        j = np.arange(M.shape[1])
        ex_home = float((M * i[:, None]).sum())
        ex_away = float((M * j[None, :]).sum())
        return ex_home, ex_away

    def top_scorelines(self, M: np.ndarray, k=3):
        """Return top-k scorelines as list of dicts: {home_goals, away_goals, prob}."""
        items = []
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                items.append((float(M[i, j]), i, j))
        items.sort(reverse=True)
        out = []
        for p, i, j in items[:k]:
            out.append({"home_goals": int(i), "away_goals": int(j), "prob": float(p)})
        return out
