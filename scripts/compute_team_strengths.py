# scripts/compute_team_strengths.py
import os
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime

IN_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "understat_team_matches.json")
OUT_STRENGTHS = os.path.join(os.path.dirname(__file__), "..", "data", "team_strengths.json")
OUT_RATINGS = os.path.join(os.path.dirname(__file__), "..", "data", "team_ratings.json")

# How many most-recent matches per team to use
MAX_MATCHES_PER_TEAM = int(os.getenv("US_MAX_MATCHES", "12"))

# Fallback league xG per team if we can't compute a mean
LEAGUE_FALLBACK_XG = float(os.getenv("LEAGUE_BASE_XG", "1.35"))


def safe_mean(values, default):
    """Return mean(values) ignoring None; default if empty."""
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return default
    return statistics.mean(vals)


def main():
    # --- Load Understat rows ---
    with open(IN_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw.get("rows", [])

    # Sort rows by (team, date) so that slicing last-N is the most recent window
    rows_sorted = sorted(
        (r for r in rows if r.get("team")),
        key=lambda r: (r.get("team"), r.get("date") or "")
    )

    per_team_for = defaultdict(list)
    per_team_against = defaultdict(list)
    all_for = []
    all_against = []

    # Collect valid xG values
    for r in rows_sorted:
        team = r.get("team")
        xf = r.get("xg_for")
        xa = r.get("xg_against")

        if isinstance(xf, (int, float)) and isinstance(xa, (int, float)):
            per_team_for[team].append(xf)
            per_team_against[team].append(xa)
            all_for.append(xf)
            all_against.append(xa)

    # League baselines
    league_xg_for = safe_mean(all_for, LEAGUE_FALLBACK_XG)
    league_xg_against = safe_mean(all_against, LEAGUE_FALLBACK_XG)

    strengths = {}
    ratings = {}

    for team in sorted(per_team_for.keys()):
        last_for = per_team_for[team][-MAX_MATCHES_PER_TEAM:]
        last_against = per_team_against[team][-MAX_MATCHES_PER_TEAM:]

        tm_for = safe_mean(last_for, league_xg_for)
        tm_against = safe_mean(last_against, league_xg_against)

        att_str = tm_for / league_xg_for if league_xg_for > 0 else 1.0
        # Def strength: higher is better (concede less than league avg)
        def_str = league_xg_against / tm_against if tm_against > 0 else 1.0

        strengths[team] = {
            "attack": round(att_str, 4),
            "defence": round(def_str, 4),
            "team_xg_for": round(tm_for, 3),
            "team_xg_against": round(tm_against, 3),
            "league_xg_for": round(league_xg_for, 3),
            "league_xg_against": round(league_xg_against, 3),
            "sample": min(len(last_for), len(last_against)),
        }

    # Derive a scalar rating compatible with generate.py
    # rating = log(attack) + log(defence); normalize to mean 0
    raw_ratings = {
        t: (math.log(max(1e-6, d["attack"])) + math.log(max(1e-6, d["defence"])))
        for t, d in strengths.items()
    }
    mean_rating = safe_mean(list(raw_ratings.values()), 0.0)
    for t, r in raw_ratings.items():
        ratings[t] = round(r - mean_rating, 6)

    os.makedirs(os.path.dirname(OUT_STRENGTHS), exist_ok=True)

    with open(OUT_STRENGTHS, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_utc": datetime.utcnow().isoformat(),
                "season_span": raw.get("seasons"),
                "league_baseline_xg": {"for": league_xg_for, "against": league_xg_against},
                "max_matches_per_team": MAX_MATCHES_PER_TEAM,
                "teams": strengths,
            },
            f,
            indent=2,
        )

    with open(OUT_RATINGS, "w", encoding="utf-8") as f:
        json.dump(ratings, f, indent=2)

    print(f"[strengths] baseline xG_for={league_xg_for:.3f} xG_against={league_xg_against:.3f}")
    print(f"[strengths] wrote strengths -> {OUT_STRENGTHS}")
    print(f"[strengths] wrote ratings   -> {OUT_RATINGS} (teams={len(ratings)})")


if __name__ == "__main__":
    main()
