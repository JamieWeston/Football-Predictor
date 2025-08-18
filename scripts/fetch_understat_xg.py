# scripts/fetch_understat_xg.py
from __future__ import annotations
import os
from pathlib import Path
from typing import List, Dict
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

DATA = (Path(__file__).resolve().parent.parent / "data").absolute()
DATA.mkdir(parents=True, exist_ok=True)
OUT = DATA / "understat_matches.csv"

LEAGUE = os.getenv("US_LEAGUE", "EPL")          # EPL, La_liga, etc. (Understat naming; EPL is fine)
SEASONS = [s.strip() for s in os.getenv("US_SEASONS", "2023,2024,2025").split(",") if s.strip()]

def _extract_rows(page, season: str) -> List[Dict]:
    """Run JS inside the page to convert matchesData (+teamsData) into a simple list of dicts."""
    return page.evaluate("""(season) => {
        try {
            const tmap = {};
            if (typeof teamsData !== 'undefined') {
                Object.values(teamsData).forEach(t => {
                    const id = t.id ?? t.team_id ?? t.id_team ?? t.id;
                    const title = t.title ?? t.team_title ?? t.name ?? t.short_title ?? t.title;
                    tmap[id] = title;
                });
            }

            const md = (typeof matchesData !== 'undefined') ? matchesData : [];
            const rows = md.map(m => {
                const date = m.datetime || m.date || m.added || null;

                const teamName = (obj, idKey, objKey, altKey) =>
                    (obj[objKey]?.title) ?? (tmap[obj[idKey]]) ?? obj[altKey] ?? null;

                const home = teamName(m, 'team_h', 'team_h', 'home_team')
                          || teamName(m, 'h', 'h', 'h_title') || m.home || null;

                const away = teamName(m, 'team_a', 'team_a', 'away_team')
                          || teamName(m, 'a', 'a', 'a_title') || m.away || null;

                const xg = m.xG ?? m.xg ?? null;
                const goals = m.goals ?? m.score ?? null;

                const xgh = Array.isArray(xg) ? (+xg[0]) :
                            + (m.xG_home ?? m.xG_h ?? m.xg1 ?? m.xG1 ?? 0);

                const xga = Array.isArray(xg) ? (+xg[1]) :
                            + (m.xG_away ?? m.xG_a ?? m.xg2 ?? m.xG2 ?? 0);

                const gh = Array.isArray(goals) ? (+goals[0]) :
                           + (m.goals_home ?? m.goals_h ?? (goals?.h ?? goals?.home) ?? 0);

                const ga = Array.isArray(goals) ? (+goals[1]) :
                           + (m.goals_away ?? m.goals_a ?? (goals?.a ?? goals?.away) ?? 0);

                return {season, date, home, away, home_xg: xgh, away_xg: xga, home_goals: gh, away_goals: ga};
            });

            return rows.filter(r => r.home && r.away && r.date);
        } catch (e) {
            return [];
        }
    }""", season)

class NoDataError(RuntimeError):
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((NoDataError, PWTimeoutError, RuntimeError)),
)
def _fetch_one_season(play, league: str, season: str) -> pd.DataFrame:
    url = f"https://understat.com/league/{league}/{season}"
    print(f"[understat] fetching {url}")

    browser = play.chromium.launch(headless=True)
    try:
        context = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
        )
        # Speed-up: block images/fonts/media
        context.route("**/*", lambda route: route.abort()
                      if route.request.resource_type in {"image", "media", "font"} else route.continue_())

        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait until matchesData is present and populated
        page.wait_for_function(
            "typeof matchesData !== 'undefined' && Array.isArray(matchesData) && matchesData.length > 0",
            timeout=30000
        )

        rows = _extract_rows(page, season)
        if not rows:
            raise NoDataError(f"matchesData empty for season {season}")

        df = pd.DataFrame(rows)
        print(f"[understat] season {season}: {len(df)} rows")
        return df
    finally:
        browser.close()

def main():
    DATA.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as play:
        frames = []
        for s in SEASONS:
            try:
                df = _fetch_one_season(play, LEAGUE, s)
                frames.append(df)
            except Exception as e:
                print(f"[understat] WARN: season {s} failed: {e}")

    if not frames:
        print("[understat] ERROR: collected 0 rows across all seasons")
        # Do NOT raise here; downstream will fallback to football-data.
        return

    all_df = pd.concat(frames, ignore_index=True)
    all_df.sort_values(["season", "date"], inplace=True, ignore_index=True)
    all_df.to_csv(OUT, index=False)
    print(f"[understat] wrote {OUT} ({len(all_df)} rows)")

if __name__ == "__main__":
    main()
