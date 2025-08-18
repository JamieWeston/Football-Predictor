# scripts/compute_team_strengths.py
import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

IN_CSV = "data/understat_matches.csv"
OUT_JSON = "data/team_strengths.json"

# Tunables via env
HALF_LIFE_DAYS = float(os.getenv("TS_HALF_LIFE_DAYS", "90"))     # time-decay half-life
RIDGE = float(os.getenv("TS_RIDGE", "5.0"))                       # regularisation strength
MIN_ROWS = int(os.getenv("TS_MIN_ROWS", "500"))                   # need enough history

EPS = 1e-6

def _decay_weight(deltas_days):
    # weight = 0.5 ** (delta_days / half_life)
    return np.power(0.5, deltas_days / HALF_LIFE_DAYS)

def fit_ratings(df: pd.DataFrame):
    """
    Solve log(xG) ~ alpha + HA*home + atk_home - def_away (and symmetrically for away)
    with ridge regularisation and sum(atk)=sum(def)=0 soft constraints.
    """
    teams = sorted(set(df["home_team"]).union(df["away_team"]))
    tidx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    # two observations per match (home xG, away xG)
    m = len(df) * 2
    # columns: [alpha, HA, atk(n), def(n)]
    p = 2 + n + n
    X = np.zeros((m + 2, p))  # +2 rows for soft constraints on sum atk/def
    y = np.zeros(m + 2)
    w = np.zeros(m + 2)

    row = 0
    for _, r in df.iterrows():
        # weights by time decay
        w_h = r["weight"]
        w_a = r["weight"]
        hi = tidx[r["home_team"]]
        ai = tidx[r["away_team"]]

        # home xG row
        X[row, 0] = 1.0                      # alpha
        X[row, 1] = 1.0                      # HA
        X[row, 2 + hi] = 1.0                 # atk_home
        X[row, 2 + n + ai] = -1.0            # -def_away
        y[row] = math.log(max(r["home_xg"], EPS))
        w[row] = w_h
        row += 1

        # away xG row
        X[row, 0] = 1.0
        X[row, 1] = 0.0
        X[row, 2 + ai] = 1.0
        X[row, 2 + n + hi] = -1.0
        y[row] = math.log(max(r["away_xg"], EPS))
        w[row] = w_a
        row += 1

    # soft constraint: sum(atk)=0 and sum(def)=0 (very small target)
    X[row, 2:2+n] = 1.0
    y[row] = 0.0
    w[row] = 0.01
    row += 1
    X[row, 2+n:2+2*n] = 1.0
    y[row] = 0.0
    w[row] = 0.01

    # Weighted ridge: solve (X^T W X + λI)β = X^T W y
    W = np.diag(w)
    XtW = X.T @ W
    A = XtW @ X
    # Ridge penalty (don’t penalise alpha/HA too much)
    reg = np.eye(p) * RIDGE
    reg[0, 0] = RIDGE * 0.01   # alpha
    reg[1, 1] = RIDGE * 0.05   # HA
    b = XtW @ y
    beta = np.linalg.solve(A + reg, b)

    alpha = float(beta[0])
    HA = float(beta[1])
    atk = beta[2:2+n]
    dfn = beta[2+n:2+2*n]

    # centre to mean zero (numerical stability)
    atk -= np.mean(atk)
    dfn -= np.mean(dfn)

    # pack
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "alpha": alpha,
        "home_adv": HA,
        "teams": {t: {"atk": float(atk[tidx[t]]), "def": float(dfn[tidx[t]])} for t in teams},
        "meta": {
            "half_life_days": HALF_LIFE_DAYS,
            "ridge": RIDGE,
            "rows_used": int(len(df)),
        },
    }
    return out

def main():
    if not os.path.exists(IN_CSV):
        raise SystemExit(f"[strengths] missing {IN_CSV}. Run fetch_understat_xg first.")
    df = pd.read_csv(IN_CSV)
    if len(df) < MIN_ROWS:
        raise SystemExit(f"[strengths] too few rows in {IN_CSV} ({len(df)} < {MIN_ROWS})")

    # time decay
    now = datetime.now(timezone.utc)
    dt = pd.to_datetime(df["date_utc"], utc=True)
    delta_days = (now - dt).dt.total_seconds() / 86400.0
    df["weight"] = _decay_weight(delta_days)

    out = fit_ratings(df)
    os.makedirs("data", exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[strengths] wrote -> {OUT_JSON} with {len(out['teams'])} teams")

if __name__ == "__main__":
    main()
