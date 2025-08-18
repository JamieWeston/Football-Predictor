#!/usr/bin/env python3
"""
Thin wrapper so GitHub Actions can run: `python -m scripts.generate`.
We keep your existing logic in scripts/pro_generate.py.
"""
from pathlib import Path
import sys

# ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from scripts.pro_generate import main  # your existing file

if __name__ == "__main__":
    raise SystemExit(main())
