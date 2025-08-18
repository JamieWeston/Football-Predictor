# Auto PR Predictions

This repo updates two files and opens a Pull Request automatically:
- `data/predictions.json` – model probabilities per match
- `data/tips.json` – one simple "best bet" per match (or "No Bet")

## How to set up (non‑technical)
1. **Create a new GitHub repo** (e.g., `pl-predictor-auto-pr`).
2. **Upload** these files (drag‑drop the ZIP contents).
3. Go to **Settings → Pages** and set "Build and deployment" to "Deploy from branch" (main).  
   Your JSON will be at: `https://<USER>.github.io/<REPO>/data/predictions.json` after you merge a PR.
4. Go to **Settings → Secrets and variables → Actions → New repository secret** and add any you have:
   - `FOOTBALL_DATA_TOKEN` (optional; if not set, script uses `data/fixtures.json` fallback)
   - `ODDS_API_KEY` (optional; no odds = tips default to "No Bet")
5. (Optional) Go to **Settings → Secrets and variables → Actions → Variables** and add `REVIEWERS` with your GitHub username (so PRs request your review).
6. Open the **Actions** tab and click **Run workflow** to test. It will open a PR with updated files.
7. Merge the PR. Your Lovable app can now read:
   - `.../data/predictions.json`
   - `.../data/tips.json`

## Where to edit later
- **Team strengths:** `data/team_ratings.csv` (or wire to your own ratings pipeline)
- **Fixtures:** `data/fixtures.json` if no API token
- **Model knobs:** `scripts/model.py` (base goals, DC rho)
- **Tips threshold:** `scripts/generate.py` (2% edge default)
- **Schedule:** `.github/workflows/predict.yml` (cron lines)

## Safety notes
- This project publishes probabilities and simple tips. It is **not betting advice**.
- Always sanity‑check outputs before merging PRs.
