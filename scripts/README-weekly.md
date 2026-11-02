# Weekly almanac refresh

`scripts/refresh_weekly.sh` runs unattended (launchd `com.ck.stratzy-weekly`). Order:
1. Auth sync: `research/sync_cookie.py` copies the longer-lived refreshToken from
   `~/claude/stratzygrokbot/session.env` into `data/stratzy_cookies.json`, then one mint probe.
   Dead token: Telegram note, exit 2, nothing else runs.
2. `scrape_all_algos.py --days 400`, `fetch_live_fills.py`
3. Regime data (`fetch_market_data.py`, `fetch_bhavcopy.py`, `regime_study.py`)
4. movers, universe, book backtest, selector, algo facts, `research/rank_all.py`, AI insight regen
5. Commit "Almanac weekly refresh <date>", push, Vercel deploy, log the live book window
6. Telegram digest (book net/MDD, selector counts vs last week, top 5, scrape coverage, auth days left)
A failed step logs and continues; only dead auth stops the run.

Logs: `logs/weekly-YYYY-MM-DD.log` (plus launchd stdout/err in `insights/launchd_weekly.*`).

By hand: `bash scripts/refresh_weekly.sh`. Preview only: `bash scripts/refresh_weekly.sh --dry-run`
(prints each step, runs just the token check). Token check alone: `python3 research/sync_cookie.py --check`.

Auth rule: one 45-day Stratzy login feeds both the copier bot and the almanac. When days left
runs low, log in and run `capture_session.py`; the bot's token is synced here automatically.

Two one-liners ck runs himself:
(a) Fix the stale remote:
    git remote set-url origin https://github.com/SirCharan/stratzy-credit-spread-report.git
(b) Move the weekly job to Sunday 10:00 IST: edit `StartCalendarInterval` in
    `~/Library/LaunchAgents/com.ck.stratzy-weekly.plist` (Weekday 0 = Sunday, Hour 10, Minute 0;
    machine clock must be IST), then:
    launchctl unload ~/Library/LaunchAgents/com.ck.stratzy-weekly.plist && launchctl load ~/Library/LaunchAgents/com.ck.stratzy-weekly.plist
