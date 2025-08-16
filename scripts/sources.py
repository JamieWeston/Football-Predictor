# scripts/sources.py (add this loader)
import os, json
from .team_names import expand_with_aliases

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")

def load_team_strengths():
    path = os.path.join(DATA_DIR, "team_strengths.json")
    if not os.path.exists(path):
        print("[warn] team_strengths.json not found")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    # expand aliases for robust lookup
    # obj: { norm_team: {attack, defence, home_adv} }
    flat = {k: v for k, v in obj.items()}
    return flat

