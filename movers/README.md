# Movers — daily EOD 1-Month tracker (ops runbook)

Ranks all 148 Stratzy algos by **1-Month return**, top-25, with day-on-day + week-on-week
rank/return deltas, biggest risers/fallers, top-25 entrants/leavers, and a **"Your Book"**
overlay from `../portfolio.json`. Pure PUBLIC API — no Chrome/DHAN auth.

## Files
- `../generate_movers.py` — the generator.
- `snapshots/YYYY-MM-DD.json` — one ranking snapshot per trading day (the diff history).
- `latest.json` — the report the SPA reads (`assets/js/views/movers.js` via `#/movers`).
- `../portfolio.json` — ck's holdings (join key = Stratzy `_id`). Update when the book changes.

## Run it
```bash
cd ~/stratzy-credit-spread-report
python3 generate_movers.py          # writes today's snapshot + latest.json
```
First run backfills the last ~10 weekdays from each algo's `rollingReturns30Day`
(annualized; the script divides by `ROLL_FACTOR=12` to match `oneMonthPnl`), so day/week
deltas populate immediately. Idempotent — safe to re-run same day.

## Deploy (makes the Movers tab live)
```bash
vercel --prod --yes --scope ck-delta-5908s-projects      # needs VERCEL_TOKEN_CKDELTA
```
NB: the default local `vercel` login (`ckdeltaexchange-1648`) cannot see the 5908 team —
deploy with the 5908-scoped token.

## Daily automation — Claude `/schedule` cloud routine
Weekday cron ~18:30 IST (`0 13 * * 1-5` UTC — tune once you see when Stratzy refreshes
`oneMonthPnl`). Routine task:
1. `git pull` this repo.
2. `python3 generate_movers.py`.
3. Read `movers/latest.json`, write a 4–6 line `narrative` into it (lead with any
   `portfolio.flags` — slipping holdings).
4. `git commit` + `git push` the new snapshot + latest.json.
5. `vercel --prod --yes` to ship.
6. POST a digest to the **@pookie trades bot** (lead with Your Book, then risers/fallers,
   entered/exited, then the narrative).

### Routine env secrets (set in the routine, never in chat)
- `GH_TOKEN` — classic PAT, `repo` scope (clone + push the private repo).
- `VERCEL_TOKEN` (= VERCEL_TOKEN_CKDELTA), `VERCEL_ORG_ID=team_QUgI2tENi0Wo8L7m2s2GoATi`,
  `VERCEL_PROJECT_ID=prj_JKE2NM4c0KBEiGiint5ogm093scg` (non-interactive `vercel --prod`).
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — the @pookie trades bot.

### Fallback (if the cloud env can't run vercel/git reliably)
Publish `movers/latest.json` to R2 (drishti/tatkaal pattern) and point `movers.js` at the
r2.dev URL — decouples data from redeploy.
