from __future__ import annotations
import os, logging
from pathlib import Path
import pandas as pd
from plpred import log as logmod
from plpred.fd_client import fetch_results

def main() -> None:
    logmod.setup()
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    token = os.getenv("FOOTBALL_DATA_TOKEN")
    comp = os.getenv("FD_COMP", "PL")
    seasons = [int(s) for s in os.getenv("FD_SEASONS", "2024,2025").split(",")]

    df = fetch_results(token, comp=comp, seasons=seasons)
    Path("data").mkdir(parents=True, exist_ok=True)
    if df.empty:
        print("[core_fetch] WARN: empty results; writing header only.")
        df = pd.DataFrame(columns=["utc_date","season","home","away","home_goals","away_goals"])

    df.to_csv("data/fd_results.csv", index=False)
    print("[core_fetch] wrote data/fd_results.csv rows:", len(df))

if __name__ == "__main__":
    main()
