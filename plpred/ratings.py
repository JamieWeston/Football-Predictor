from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Dict, Any
import pandas as pd

def _parse_date(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception:
        return datetime.now(timezone.utc)

def _half_life_weight(age_days: float, half_life_days: float) -> float:
    if half_life_days <= 0: return 1.0
    return 0.5 ** (age_days / half_life_days)

def build_ratings(df: pd.DataFrame,
                  half_life_days: float = 180.0,
                  min_games_cap: int = 3,
                  max_home_adv: float = 1.25,
                  min_home_adv: float = 1.05) -> Dict[str, Any]:
    if df.empty:
        return {"league_avg_gpg": 1.35, "home_adv": 1.10, "draw_scale": 1.00, "teams": {}}

    df = df.copy()
    now = datetime.now(timezone.utc)
    df["kick_dt"] = df["utc_date"].apply(_parse_date)
    df["age_days"] = (now - df["kick_dt"]).dt.total_seconds() / 86400.0
    df["w"] = df["age_days"].apply(lambda d: _half_life_weight(d, half_life_days)).clip(0.05, 1.0)

    def _agg(df2: pd.DataFrame):
        h = df2.groupby("home").apply(lambda g: pd.Series({
            "gf_h": (g["home_goals"]*g["w"]).sum(),
            "ga_h": (g["away_goals"]*g["w"]).sum(),
            "gp_h": g["w"].sum()
        }))
        a = df2.groupby("away").apply(lambda g: pd.Series({
            "gf_a": (g["away_goals"]*g["w"]).sum(),
            "ga_a": (g["home_goals"]*g["w"]).sum(),
            "gp_a": g["w"].sum()
        }))
        s = h.join(a, how="outer").fillna(0.0).reset_index().rename(columns={"index":"team"})
        s["gf"] = s["gf_h"] + s["gf_a"]
        s["ga"] = s["ga_h"] + s["ga_a"]
        s["gp"] = s["gp_h"] + s["gp_a"]
        return s

    base = _agg(df)
    if base["gp"].sum() <= 0:
        return {"league_avg_gpg": 1.35, "home_adv": 1.10, "draw_scale": 1.00, "teams": {}}

    lg_gpg = ((base["gf"].sum() + base["ga"].sum()) / (2 * base["gp"].sum()))
    lg_gpg = max(float(lg_gpg), 0.01)

    h_gpg = base["gf_h"].sum() / max(base["gp_h"].sum(), 1e-6)
    a_gpg = base["gf_a"].sum() / max(base["gp_a"].sum(), 1e-6)
    home_adv = h_gpg / max(a_gpg, 1e-6)
    home_adv = float(min(max(home_adv, min_home_adv), max_home_adv))

    teams = {t: {"att":1.0, "def":1.0, "att_h":1.0,"def_h":1.0,"att_a":1.0,"def_a":1.0} for t in base["team"]}

    def _rates_from_agg(s: pd.DataFrame):
        out = {}
        for _, r in s.iterrows():
            gp = max(r["gp"], 1e-6)
            gp_h = max(r["gp_h"], 1e-6)
            gp_a = max(r["gp_a"], 1e-6)
            att  = (r["gf"]/gp) / lg_gpg
            deff = lg_gpg / max((r["ga"]/gp), 1e-6)
            att_h = (r["gf_h"]/gp_h) / lg_gpg if r["gp_h"]>0 else att
            deff_h = lg_gpg / max((r["ga_h"]/gp_h), 1e-6) if r["gp_h"]>0 else deff
            att_a = (r["gf_a"]/gp_a) / lg_gpg if r["gp_a"]>0 else att
            deff_a = lg_gpg / max((r["ga_a"]/gp_a), 1e-6) if r["gp_a"]>0 else deff
            out[r["team"]] = {
                "att": float(att), "def": float(deff),
                "att_home": float(att_h), "def_home": float(deff_h),
                "att_away": float(att_a), "def_away": float(deff_a),
                "games": float(r["gp"]),
            }
        return out

    rates0 = _rates_from_agg(base)
    teams.update({k: {**teams[k], **v} for k,v in rates0.items()})

    adj_rows = []
    for _, m in df.iterrows():
        h, a = m["home"], m["away"]
        w = m["w"]
        hg, ag = float(m["home_goals"]), float(m["away_goals"])
        op_def_for_h = teams.get(a, {}).get("def_away", 1.0)
        op_att_for_h = teams.get(a, {}).get("att_away", 1.0)
        op_def_for_a = teams.get(h, {}).get("def_home", 1.0)
        op_att_for_a = teams.get(h, {}).get("att_home", 1.0)
        adj_rows.append({
            "home": h, "away": a, "w": w,
            "gf_h_adj": hg / max(op_def_for_h, 0.2),
            "ga_h_adj": ag / max(op_att_for_h, 0.2),
            "gf_a_adj": ag / max(op_def_for_a, 0.2),
            "ga_a_adj": hg / max(op_att_for_a, 0.2),
        })
    adj = pd.DataFrame(adj_rows)
    h2 = adj.groupby("home").apply(lambda g: pd.Series({
        "gf_h": (g["gf_h_adj"]*g["w"]).sum(),
        "ga_h": (g["ga_h_adj"]*g["w"]).sum(),
        "gp_h": g["w"].sum()
    }))
    a2 = adj.groupby("away").apply(lambda g: pd.Series({
        "gf_a": (g["gf_a_adj"]*g["w"]).sum(),
        "ga_a": (g["ga_a_adj"]*g["w"]).sum(),
        "gp_a": g["w"].sum()
    }))
    s2 = h2.join(a2, how="outer").fillna(0.0).reset_index().rename(columns={"index":"team"})
    s2["gf"] = s2["gf_h"] + s2["gf_a"]; s2["ga"] = s2["ga_h"] + s2["ga_a"]; s2["gp"] = s2["gp_h"] + s2["gp_a"]

    rates = _rates_from_agg(s2)

    obs_draw = ( (df["home_goals"]==df["away_goals"]).astype(float) * df["w"] ).sum() / max(df["w"].sum(),1e-6)
    mean_att = float(pd.Series([v["att"] for v in rates.values()]).mean()) if rates else 1.0
    mean_def = float(pd.Series([v["def"] for v in rates.values()]).mean()) if rates else 1.0
    lam_bar = lg_gpg * mean_att * mean_def * home_adv
    mu_bar  = lg_gpg * mean_att * mean_def
    def _pois(k, lam): return math.exp(-lam) * (lam**k) / math.factorial(k)
    pd_model = sum(_pois(g,lam_bar)*_pois(g,mu_bar) for g in range(10))
    draw_scale = float(max(min((obs_draw / max(pd_model,1e-6)), 1.10), 0.90))

    out_teams = {}
    for t, v in rates.items():
        out_teams[t] = {
            "att": round(max(min(v["att"], 1.8), 0.6), 4),
            "def": round(max(min(v["def"], 1.8), 0.6), 4),
            "att_home": round(max(min(v["att_home"], 1.9), 0.5), 4),
            "def_home": round(max(min(v["def_home"], 1.9), 0.5), 4),
            "att_away": round(max(min(v["att_away"], 1.9), 0.5), 4),
            "def_away": round(max(min(v["def_away"], 1.9), 0.5), 4),
            "games": int(max(v.get("games",0.0), 0.0))
        }

    return {
        "league_avg_gpg": round(lg_gpg,3),
        "home_adv": round(home_adv,3),
        "draw_scale": round(draw_scale,3),
        "teams": out_teams
    }
