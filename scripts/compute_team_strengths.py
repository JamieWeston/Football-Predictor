# scripts/compute_team_strengths.py
import os, json, math, statistics
from datetime import datetime
from scripts.team_names import norm, expand_with_aliases

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, "data")
IN_PATH = os.path.join(DATA, "understat_team_matches.json")
OUT_PATH = os.path.join(DATA, "team_strengths.json")

# Tunable knobs
HALF_LIFE_MATCHES = 10          # exponential decay half-life in matches
MIN_MATCHES_FOR_CLUB_HA = 15    # need at least this many home matches to estimate club-HA
GLOBAL_HA_PRIOR = 0.20          # log-goal prior (approx +20% home scoring)
REG_TO_MEAN_WEIGHT = 6.0        # pseudo-matches to pull towards league mean
CLIP_ATTACK = (-0.6, 0.6)       # avoid extreme logs
CLIP_DEF    = (-0.6, 0.6)

def _exp_decay_weights(n, half_life):
    # weights for most-recent-first arrays length n
    lam = math.log(2) / max(1e-9, half_life)
    return [math.exp(-lam*i) for i in range(n)]

def main():
    # load rows
    if not os.path.exists(IN_PATH):
        raise SystemExit(f"[err] missing {IN_PATH}; run fetch_understat_xg.py first")

    with open(IN_PATH, "r", encoding="utf-8") as f:
        rows = json.load(f)["rows"]

    # group matches by team_norm, sort by date ascending
    by_team = {}
    for r in rows:
        tn = norm(r["team"])
        by_team.setdefault(tn, []).append(r)
    for tn in by_team:
        by_team[tn].sort(key=lambda x: x["date"])

    # league means (overall xG for/against per match)
    all_xg_for = [r["xg_for"] for r in rows]
    all_xg_ag  = [r["xg_against"] for r in rows]
    league_xg_for = statistics.mean(all_xg_for) if all_xg_for else 1.35
    league_xg_ag  = statistics.mean(all_xg_ag)  if all_xg_ag  else 1.35

    strengths = {}
    club_ha = {}  # club-specific HA in log-scale

    # compute club-specific HA if enough data
    for tn, games in by_team.items():
        home_for = []; home_ag = []
        away_for = []; away_ag = []
        for g in games:
            if g["is_home"]:
                home_for.append(g["xg_for"]); home_ag.append(g["xg_against"])
            else:
                away_for.append(g["xg_for"]); away_ag.append(g["xg_against"])
        if len(home_for) >= MIN_MATCHES_FOR_CLUB_HA and len(away_for) >= MIN_MATCHES_FOR_CLUB_HA:
            # estimate HA as excess of home for vs away for
            m_home = statistics.mean(home_for)
            m_away = statistics.mean(away_for)
            # avoid zero
            m_home = max(0.05, m_home); m_away = max(0.05, m_away)
            ha = math.log(m_home / m_away)
            # shrink towards global prior
            w = min(1.0, (len(home_for)+len(away_for)) / 50.0)
            club_ha[tn] = (1-w) * GLOBAL_HA_PRIOR + w * ha

    # global HA fallback
    global_ha = GLOBAL_HA_PRIOR

    # per-team rolling strengths with exponential decay
    for tn, games in by_team.items():
        # use last 38 matches max for rolling (about a season)
        last = games[-60:]  # allow up to ~1.5 seasons
        # most-recent first for weights
        last_rev = list(reversed(last))
        w = _exp_decay_weights(len(last_rev), HALF_LIFE_MATCHES)
        w_sum = sum(w) if w else 1.0

        xgf = sum(g["xg_for"] * w[i] for i, g in enumerate(last_rev)) / w_sum if w_sum else league_xg_for
        xga = sum(g["xg_against"] * w[i] for i, g in enumerate(last_rev)) / w_sum if w_sum else league_xg_ag

        # regression to league mean (pseudo-matches)
        n_eff = min(len(last), 60)
        reg_w = REG_TO_MEAN_WEIGHT
        xgf_reg = (xgf * n_eff + league_xg_for * reg_w) / (n_eff + reg_w)
        xga_reg = (xga * n_eff + league_xg_ag  * reg_w) / (n_eff + reg_w)

        # convert to log strengths relative to league mean
        atk = math.log(max(0.05, xgf_reg) / max(0.05, league_xg_for))
        dfn = math.log(max(0.05, league_xg_ag) / max(0.05, xga_reg))  # defend: higher is better

        # clip extremes
        atk = max(CLIP_ATTACK[0], min(CLIP_ATTACK[1], atk))
        dfn = max(CLIP_DEF[0],    min(CLIP_DEF[1],    dfn))

        strengths[tn] = {
            "attack": atk,
            "defence": dfn,
            "home_adv": club_ha.get(tn, global_ha)
        }

    # write
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(strengths, f, indent=2)
    print(f"[strengths] wrote {len(strengths)} teams to {OUT_PATH}")

if __name__ == "__main__":
    main()
