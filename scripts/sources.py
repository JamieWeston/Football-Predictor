import os, json, requests
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

def load_fixtures():
    """Try API first (if token), else fallback to data/fixtures.json"""
    token = os.getenv("FOOTBALL_DATA_TOKEN","").strip()
    # Placeholder: you can swap to your preferred provider.
    if token:
        # Example: football-data.org free endpoint structure (pseudo; adjust to provider)
        # Here we simply fallback due to provider T&Cs. Use your own API in production.
        pass
    # Fallback
    with open(os.path.join(DATA_DIR, "fixtures.json"), "r") as f:
        return json.load(f)["fixtures"]

def load_team_ratings():
    import csv
    ratings = {}
    with open(os.path.join(DATA_DIR, "team_ratings.csv"), newline="") as f:
        reader = csv.DictReader(f)
        vals = [float(r["ExpPts"]) for r in reader]
        f.seek(0); reader = csv.DictReader(f)
        mu = sum(vals)/len(vals)
        sd = (sum((v-mu)**2 for v in vals)/len(vals))**0.5
        for row in reader:
            z = (float(row["ExpPts"]) - mu) / sd if sd>0 else 0.0
            ratings[row["Team"]] = z
    return ratings

def fetch_best_odds():
    """Optional: pull odds from an API. If no API key set, return empty list (no odds)."""
    key = os.getenv("ODDS_API_KEY","").strip()
    if not key:
        return []
    # Placeholder for your odds provider call:
    # Example retrieval and mapping to:
    # [{match_id, market, selection, decimal_odds, source, fetched_utc}, ...]
    # For now, return empty and let tips default to 'No Bet' when no odds available.
    return []
