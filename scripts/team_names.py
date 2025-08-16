# scripts/team_names.py
import re

def norm(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"[^\w\s&]", " ", s)
    s = re.sub(r"\b(fc|afc|cf)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

CANONICAL_ALIASES = {
    "wolverhampton wanderers": {"wolverhampton", "wolves"},
    "tottenham hotspur": {"tottenham", "spurs"},
    "manchester united": {"man utd", "man united", "manchester utd"},
    "manchester city": {"man city"},
    "newcastle united": {"newcastle utd"},
    "leeds united": {"leeds utd"},
    "nottingham forest": {"nottm forest", "nottingham"},
    "brighton & hove albion": {"brighton", "brighton and hove albion"},
    "west ham united": {"west ham"},
    "crystal palace": {"palace"},
    "aston villa": {"villa"},
    "afc bournemouth": {"bournemouth"},
    "sunderland afc": {"sunderland"},
    "brentford": set(),
    "fulham": set(),
    "everton": set(),
    "chelsea": set(),
    "arsenal": set(),
    "liverpool": set(),
    "burnley": set(),
    "wolves": {"wolverhampton wanderers"},
}

def expand_with_aliases(raw: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in raw.items():
        out[norm(k)] = float(v)
    for canonical, syns in CANONICAL_ALIASES.items():
        nk = norm(canonical)
        if nk in out:
            for s in syns:
                out[norm(s)] = out[nk]
    extras = {}
    for k in list(out.keys()):
        if "&" in k:
            extras[k.replace("&", "and")] = out[k]
            extras[k.replace("&", "")] = out[k]
    out.update(extras)
    return out
