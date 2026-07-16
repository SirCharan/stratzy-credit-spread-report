# Movers — daily EOD multi-horizon tracker (ops runbook)

Ranks all 148 Stratzy algos across **three horizons** — a **1-Day** and **1-Week** leaderboard
plus the top-25 by **1-Month return** — with day-on-day + week-on-week deltas, biggest
risers/fallers, top-25 entrants/leavers, a **"Your Book"** overlay from `../portfolio.json`, and
an **AI insight** block (add/trim/exit calls on the book + watchlist + market read + risk flags).
Pure PUBLIC API — no Chrome/DHAN auth.

## Horizons & sources (`GET /api/web/algo/list`)
- **1-Month** — `oneMonthPnl` (the ranking spine; top-25 table + entered/exited).
- **1-Week** — `sevenDayPnl` (present for all 148) → `week_board {leaders,laggards}` with DoD/WoW
  change of the 7D number.
- **1-Day** — latest point of each algo's `performance` series (per-session return). No headline
  1-day field exists and algos trade at different cadences, so `day_board` only includes algos whose
  most-recent session == `day_board.as_of_date` (~70/148 on a normal day); the rest didn't trade it.

## `latest.json` shape (consumers: SPA `#/movers` + @pookie `/movers`)
Numeric fields written by `generate_movers.py`: `top`, `day_board`, `week_board`, `risers`,
`fallers`, `entered`, `exited`, `portfolio`. Snapshots are **v2** — each algo row now carries
`seven_day_pnl` + `day_pnl` (when it traded), so 1D/1W DoD/WoW deltas populate forward (v1 files
still load; missing fields → null).

`ai_insight` is emitted as `null` by python and **filled by the daily /schedule routine** (below):
```jsonc
ai_insight: {
  generated_at, model,
  market_read: "2-4 sentences: what's working now (category/regime), notable gainers/losers/entrants",
  portfolio_actions: [ { id, name, action: "add"|"trim"|"hold"|"exit", rationale } ],  // one per holding
  watchlist:         [ { id, name, rationale } ],   // 1-3 non-held, climbing, ideally in research
  risk_flags:        [ "concentration / slipping / drawdown notes" ]
}
```

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
vercel --prod --yes --scope ckdeltaexchange-1648s-projects
```
Git-connected to **SirCharan/stratzy-credit-spread-report** — push to `main` also auto-deploys.
Default local `vercel` login (`ckdeltaexchange-1648`) owns this project.

## Automation — LOCAL launchd loop (canonical since 2026-07-08)
A headless cloud loop is impossible (the deep pipeline needs a live DHAN Chrome session on the
Mac). The loop is now local launchd — see `../scripts/` and `../CONTEXT.md`:
- **`scripts/refresh_daily.sh`** (`com.ck.stratzy-daily`, weekdays 18:30 IST): movers + universe
  numbers → commit → deploy → optional @pookie digest. No auth. This supersedes the old cloud
  routine below.
- **`scripts/refresh_weekly.sh`** (`com.ck.stratzy-weekly`, Sun 10:00 IST): full deep pipeline +
  `generate_algo_facts.py` + AI regen (per-algo profiles + this movers `ai_insight`, via `claude -p`
  driving `workflows/algo-insights.mjs`) + deploy. Needs DHAN Chrome login; fails-soft.
- Install: `cp scripts/launchd/*.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.ck.stratzy-*.plist`.

### (Legacy) Claude `/schedule` cloud routine — NOT used (blocked on GitHub-App connect)
Weekday cron ~18:30 IST (`0 13 * * 1-5` UTC — tune once you see when Stratzy refreshes
`oneMonthPnl`). Routine task:
1. `git pull` this repo.
2. `python3 generate_movers.py`.
3. Read `movers/latest.json` and write **both**:
   - a 4–6 line `narrative` (lead with any `portfolio.flags` — slipping holdings);
   - the structured **`ai_insight`** object (schema above). Ground every call in the data already
     in the file: `portfolio.holdings` (rank, `one_month_pnl`, `seven_day_pnl`, `day_pnl`,
     `dod_rank_delta`, `slipping`), `day_board`/`week_board` (who's leading each horizon), and
     `entered`/`exited`. One `portfolio_actions` entry **per holding** — `add` for strong/climbing,
     `trim` for slipping, `exit` for persistent losers, `hold` otherwise, each with a one-line
     rationale. `watchlist` = 1–3 non-held climbers (prefer `in_research`). `risk_flags` =
     concentration / slipping / drawdown. Keep it decision-useful, not flowery.
4. `git commit` + `git push` the new snapshot + latest.json.
5. `vercel --prod --yes` to ship (1648 scope).
6. POST a digest to the **@pookie trades bot** in this order: **portfolio actions first**
   (add/trim/exit), then 1-Day + 1-Week leaders, then risers/fallers + entered/exited, then the
   market read. (The interactive `/movers` command in the `zerodha-tg-bot` repo serves this same
   `latest.json`, so once it's shipped both the push and on-demand replies show the same insight.)

### Routine env secrets (set in the routine, never in chat)
- `GH_TOKEN` — classic PAT, `repo` scope (clone + push the private repo).
- `VERCEL_ORG_ID=team_D1J75A4fenW3rooePNxiubx9`,
  `VERCEL_PROJECT_ID=prj_OQenVHe8815WyOiuZazQ0Hjbitrz` (non-interactive `vercel --prod`).
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — the @pookie trades bot.

### Fallback (if the cloud env can't run vercel/git reliably)
Publish `movers/latest.json` to R2 (drishti/tatkaal pattern) and point `movers.js` at the
r2.dev URL — decouples data from redeploy.
