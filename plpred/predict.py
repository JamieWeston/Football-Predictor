# plpred/predict.py
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Tuple, List, Any


# --------------------------
# Canonicalisation & mapping
# --------------------------

_ALIAS_OVERRIDES = {
    # Add only when needed; resolver already handles FC/AFC/punctuation/case.
    # Examples:
    # "manchester utd": "manchester united",
    # "wolves": "wolverhampton wanderers",
    # "spurs": "tottenham hotspur",
}

_CANON_RE = re.compile(r"[^a-z0-9]+")


def canon_team(name: str) -> str:
    """Normalise a team display name to a canonical key."""
    if not name:
        return ""
    s = name.lower().strip()
    s = s.replace("&", "and")
    # Remove explicit FC/AFC tokens
    s = re.sub(r"\b(?:afc|a\.?f\.?c\.?|fc)\b", "", s)
    # Collapse punctuation/whitespace
    s = _CANON_RE.sub(" ", s).strip()
    s = re.sub(r"\s+", " ", s)
    # Alias overrides (if any)
    s = _ALIAS_OVERRIDES.get(s, s)
    return s


def _build_canon_index(team_dict: Dict[str, Any]) -> Dict[str, str]:
    """
    Build an index mapping canonical form -> original key for a ratings['teams'] dict.
    Keys in ratings might be 'Arsenal' or 'Arsenal FC'; the index lets us resolve either.
    """
    idx = {}
    for k in team_dict.keys():
        idx[canon_team(k)] = k
    return idx


def resolve_team_key(name: str, ratings: Dict[str, Any]) -> Tuple[str | None, str]:
    """
    Map a fixture name to a ratings key.

    Returns (ratings_key_or_None, resolution_note).
    """
    teams = ratings.get("teams", {})
    if not teams:
        return None, "no-teams-in-ratings"

    cidx = _build_canon_index(teams)

    c = canon_team(name)
    # Direct canonical hit
    if c in cidx:
        return cidx[c], "direct"

    # Very simple token-based fallback: pick the ratings key with max token overlap
    tokens = set(c.split())
    best_key, best_score = None, -1
    for ck, original in cidx.items():
        score = len(tokens.intersection(set(ck.split())))
        if score > best_score:
            best_key, best_score = original, score

    if best_score > 0:
        return best_key, "token-match"

    return None, "unmatched"


# --------------------------
# Outcome probabilities (Poisson + draw scaling)
# --------------------------

def _pois(k: int, lam: float) -> float:
    lam = max(float(lam), 1e-9)
    return math.exp(-lam) * lam**k / math.factorial(k)


def outcome_probs(lam_home: float, lam_away: float, draw_scale: float = 1.0) -> Tuple[float, float, float]:
    """
    Return (P_home, P_draw, P_away) using independent Poisson with optional draw scaling.
    """
    max_g = 12  # cap to keep numerical stable & fast
    ph = pd = pa = 0.0

    for i in range(0, max_g + 1):
        pi = _pois(i, lam_home)
        for j in range(0, max_g + 1):
            pj = _pois(j, lam_away)
            p = pi * pj
            if i > j:
                ph += p
            elif i == j:
                pd += p
            else:
                pa += p

    if draw_scale != 1.0:
        # Reweight draws and renormalise
        pd *= draw_scale
        s = ph + pd + pa
        if s > 0:
            ph /= s
            pd /= s
            pa /= s

    return ph, pd, pa


def top_scorelines(lam_home: float, lam_away: float, k: int = 3, cap: int = 8) -> List[Dict[str, Any]]:
    """
    Return top-k most likely scorelines with probs.
    """
    out = []
    for i in range(0, cap + 1):
        pi = _pois(i, lam_home)
        for j in range(0, cap + 1):
            pj = _pois(j, lam_away)
            out.append({"home_goals": i, "away_goals": j, "prob": pi * pj})
    out.sort(key=lambda r: r["prob"], reverse=True)
    return out[:k]


# --------------------------
# Expected goals per fixture
# --------------------------

@dataclass
class Strengths:
    att: float = 1.0
    deff: float = 1.0  # 'def' is reserved in Python, so use 'deff'
    att_h: float = 1.0
    deff_h: float = 1.0
    att_a: float = 1.0
    deff_a: float = 1.0


def _get_strengths(key: str | None, ratings: Dict[str, Any]) -> Strengths:
    if not key:
        return Strengths()
    t = ratings.get("teams", {}).get(key, {})
    return Strengths(
        att=float(t.get("att", 1.0)),
        deff=float(t.get("def", 1.0)),
        att_h=float(t.get("att_h", t.get("att", 1.0))),
        deff_h=float(t.get("def_h", t.get("def", 1.0))),
        att_a=float(t.get("att_a", t.get("att", 1.0))),
        deff_a=float(t.get("def_a", t.get("def", 1.0))),
    )


def expected_goals_for_pair(home_name: str, away_name: str, ratings: Dict[str, Any]) -> Tuple[float, float, Dict[str, Any]]:
    """
    Compute (lambda_home, lambda_away, debug_note) using league baselines and team strengths.
    This is where we ensure **per-match variation** by actually using the resolved team strengths.
    """
    # League baselines; keep previous defaults if not present
    base_home = float(ratings.get("base_home_xg", ratings.get("league_home_xg", 1.45)))
    base_away = float(ratings.get("base_away_xg", ratings.get("league_away_xg", 1.35)))

    key_h, how_h = resolve_team_key(home_name, ratings)
    key_a, how_a = resolve_team_key(away_name, ratings)

    sh = _get_strengths(key_h, ratings)
    sa = _get_strengths(key_a, ratings)

    # Attack vs defence: multiplicative adjustment
    lam_h = base_home * sh.att_h / max(sa.deff_a, 1e-6)
    lam_a = base_away * sa.att_a / max(sh.deff_h, 1e-6)

    # Sanity caps
    lam_h = max(0.2, min(lam_h, 3.5))
    lam_a = max(0.2, min(lam_a, 3.5))

    debug = {
        "home_name": home_name,
        "away_name": away_name,
        "home_key": key_h,
        "away_key": key_a,
        "resolve_home": how_h,
        "resolve_away": how_a,
        "lam_home": round(lam_h, 3),
        "lam_away": round(lam_a, 3),
    }
    return lam_h, lam_a, debug
