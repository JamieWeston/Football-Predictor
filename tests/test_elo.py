import pandas as pd
from plpred.elo import build_elo, elo_match_probs

def test_build_elo_minimal():
    df = pd.DataFrame([
        {"utc_date":"2024-08-10T12:00:00Z","home":"A","away":"B","home_goals":2,"away_goals":1},
        {"utc_date":"2024-08-20T12:00:00Z","home":"B","away":"A","home_goals":0,"away_goals":1},
    ])
    e = build_elo(df)
    assert "teams" in e and "draw_nu" in e and e["scale"] > 0

def test_elo_probs_sum_to_one():
    pH,pD,pA = elo_match_probs(1520, 1500, home_adv_points=60, scale=400, draw_nu=1.0)
    s = pH+pD+pA
    assert 0.99 < s < 1.01 and 0 < pH < 1 and 0 < pD < 1 and 0 < pA < 1
