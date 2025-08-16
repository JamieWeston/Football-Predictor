# scripts/smoke.py
import json, math, statistics as stats
from pathlib import Path
import sys

PRED_PATH = Path("data/predictions.json")

def near(a, b, eps=0.025):
    return abs(a - b) <= eps

def fail(msg):
    print(f"[SMOKE FAIL] {msg}")
    sys.exit(1)

def warn(msg):
    print(f"[SMOKE WARN] {msg}")

def main():
    if not PRED_PATH.exists():
        fail(f"Missing {PRED_PATH}")

    data = json.loads(PRED_PATH.read_text(encoding="utf-8"))
    preds = data.get("predictions", [])
    if not preds:
        fail("No predictions found.")

    if len(preds) < 5:
        warn(f"Only {len(preds)} fixtures present. Is the window too short?")

    # 1) Basic probability sanity per match
    uniq_triples = set()
    home_probs = []
    draw_probs  = []
    away_probs  = []
    btts_yes    = []
    over_25     = []
    zeros_xg    = 0

    for p in preds:
        probs = p.get("probs", {})
        btts  = p.get("btts", {})
        tot   = p.get("totals_2_5", {})
        xg    = p.get("xg", {"home": None, "away": None})

        h = float(probs.get("home", 0.0))
        d = float(probs.get("draw", 0.0))
        a = float(probs.get("away", 0.0))
        s = h + d + a
        if not near(s, 1.0, 0.03):
            fail(f"{p.get('match_id')} home/draw/away do not sum to 1 (got {s:.3f})")

        for v in (h, d, a):
            if v < 0 or v > 1:
                fail(f"{p.get('match_id')} probability out of range (0..1)")

        home_probs.append(h); draw_probs.append(d); away_probs.append(a)
        uniq_triples.add((round(h,4), round(d,4), round(a,4)))

        by = float(btts.get("yes", 0.0)); bn = float(btts.get("no", 0.0))
        if not near(by + bn, 1.0, 0.03):
            fail(f"{p.get('match_id')} BTTS yes/no not summing to 1 (got {(by+bn):.3f})")
        btts_yes.append(by)

        ov = float(tot.get("over", 0.0)); un = float(tot.get("under", 0.0))
        if not near(ov + un, 1.0, 0.03):
            fail(f"{p.get('match_id')} O/U not summing to 1 (got {(ov+un):.3f})")
        over_25.append(ov)

        xh = xg.get("home", 0.0); xa = xg.get("away", 0.0)
        if xh is None or xa is None:
            fail(f"{p.get('match_id')} xG missing values")
        if (xh == 0 and xa == 0):
            zeros_xg += 1

    # 2) If all triples identical, something is off (e.g., constant strengths)
    if len(uniq_triples) == 1 and len(preds) >= 5:
        fail("All matches share the exact same home/draw/away triple. Ratings look constant.")

    # 3) Spread should exist (not microscopic variance)
    try:
        if len(preds) >= 6:
            stdev_h = stats.pstdev(home_probs)
            stdev_d = stats.pstdev(draw_probs)
            stdev_a = stats.pstdev(away_probs)
            if max(stdev_h, stdev_d, stdev_a) < 0.01:
                fail(f"Very low variance across matches (h={stdev_h:.4f}, d={stdev_d:.4f}, a={stdev_a:.4f})")
    except Exception as e:
        warn(f"Variance calc skipped: {e}")

    # 4) Too many zero-xG rows likely means upstream parsing failed
    if zeros_xg > len(preds) * 0.5:
        warn(f"Over half of fixtures have xG=0–0 ({zeros_xg}/{len(preds)}). Upstream fetch might be stale.")

    print(f"[SMOKE OK] {len(preds)} predictions look sane.")
    sys.exit(0)

if __name__ == "__main__":
    main()
