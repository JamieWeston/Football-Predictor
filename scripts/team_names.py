# scripts/team_names.py
import re

CANON = {
    # Football-data -> Understat canonical
    "manchester united": "Manchester United",
    "man united": "Manchester United",
    "man utd": "Manchester United",
    "manchester city": "Manchester City",
    "man city": "Manchester City",
    "tottenham": "Tottenham Hotspur",
    "tottenham hotspur": "Tottenham Hotspur",
    "spurs": "Tottenham Hotspur",
    "wolves": "Wolverhampton Wanderers",
    "wolverhampton": "Wolverhampton Wanderers",
    "wolverhampton wanderers": "Wolverhampton Wanderers",
    "newcastle": "Newcastle United",
    "newcastle united": "Newcastle United",
    "brighton": "Brighton",
    "brighton & hove albion": "Brighton",
    "bournemouth": "Bournemouth",
    "west ham": "West Ham United",
    "west ham united": "West Ham United",
    "nottingham forest": "Nottingham Forest",
    "nottm forest": "Nottingham Forest",
    "everton": "Everton",
    "fulham": "Fulham",
    "brentford": "Brentford",
    "aston villa": "Aston Villa",
    "burnley": "Burnley",
    "crystal palace": "Crystal Palace",
    "chelsea": "Chelsea",
    "arsenal": "Arsenal",
    "leeds united": "Leeds United",
    "leeds": "Leeds United",
    "liverpool": "Liverpool",
}

def canonical(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return CANON.get(key, None) or name
