#!/usr/bin/env python3
"""
Dispatcher so Actions can run: `python -m scripts.generate`
Set PREDICT_MODE=core (default) or PREDICT_MODE=pro
"""
from pathlib import Path
import os
import sys

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from scripts.core_generate import main as core_main  # always available
try:
    from scripts.pro_generate import main as pro_main
except Exception:
    pro_main = None  # pro is optional

def main() -> int:
    mode = os.getenv("PREDICT_MODE", "core").lower()
    if mode == "pro":
        if pro_main is None:
            print("[dispatcher] pro_generate not available, falling back to core.")
            return core_main()
        print("[dispatcher] running PRO generator")
        return pro_main()
    print("[dispatcher] running CORE generator")
    return core_main()

if __name__ == "__main__":
    raise SystemExit(main())
