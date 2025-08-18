import pandas as pd
from plpred.fd_client import fetch_results, fetch_fixtures

class DummyResp:
    def __init__(self, json_data, status=200): self._j, self.status_code = json_data, status
    def json(self): return self._j
    def raise_for_status(self):
        if self.status_code >= 400: raise Exception("HTTP " + str(self.status_code))

def test_fetch_results_happy():
    def fake_get(url, params, headers):
        return DummyResp({"matches":[
            {"utcDate":"2024-08-10T12:00:00Z",
             "homeTeam":{"name":"A"}, "awayTeam":{"name":"B"},
             "score":{"fullTime":{"home":2,"away":1}}}
        ]})
    df = fetch_results(None, "PL", [2024], http_get=fake_get)
    assert not df.empty and list(df.columns)==["utc_date","season","home","away","home_goals","away_goals"]

def test_fetch_fixtures_error_returns_empty():
    def bad_get(url, params, headers): return DummyResp({}, status=500)
    fx = fetch_fixtures(None, "PL", "2025-08-01", "2025-08-31", http_get=bad_get)
    assert fx == []
