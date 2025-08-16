# scripts/archive_predictions.py
import os, json
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HIST_DIR = os.path.join(DATA_DIR, "history")

def main():
    src = os.path.join(DATA_DIR, "predictions.json")
    if not os.path.exists(src):
        print("[archive] no predictions.json found")
        return
    with open(src,"r") as f:
        js = json.load(f)
    ts = js.get("generated_utc") or datetime.now(timezone.utc).isoformat()
    ts_compact = ts.replace(":","").replace("-","").replace("+00:00","Z")
    os.makedirs(HIST_DIR, exist_ok=True)
    out = os.path.join(HIST_DIR, f"preds_{ts_compact}.json")
    with open(out,"w") as f:
        json.dump(js, f, indent=2)
    print(f"[archive] wrote {out}")

if __name__ == "__main__":
    main()
