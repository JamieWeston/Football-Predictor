import pandas as pd
from plpred.ratings import build_ratings

def test_build_ratings_happy():
    df = pd.DataFrame([
        {"utc_date":"2024-08-10T12:00:00Z","home":"A","away":"B","home_goals":2,"away_goals":1},
        {"utc_date":"2024-08-20T12:00:00Z","home":"B","away":"A","home_goals":0,"away_goals":1},
    ])
    r = build_ratings(df, half_life_days=365)
    assert "teams" in r and "league_avg_gpg" in r and r["home_adv"] >= 1.0

def test_build_ratings_empty_neutral():
    df = pd.DataFrame(columns=["utc_date","home","away","home_goals","away_goals"])
    r = build_ratings(df)
    assert r["teams"] == {} and r["league_avg_gpg"] > 0
