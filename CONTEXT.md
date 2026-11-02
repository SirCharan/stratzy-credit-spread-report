# CONTEXT — The Stratzy Almanac

Onboarding doc for this repo. Live: **https://stratzy-credit-spread-report.vercel.app** (Vercel team 5908 / `ck-delta`). Last reconfirmed 2026-07-06.

## What it is
A quant research broadsheet that **reverse-engineers Stratzy.in** (an Indian SEBI algo-advisory marketplace of 148 algos). Rather than trust Stratzy's headline "1-Year Return %", it pulls each algo's per-trade history and **recomputes P&L from raw fills** into the unit a NIFTY trader reads instinctively — **net premium points and ₹ per 1 lot (65 qty)**. Two universes analysed in depth: **credit spreads** (premium-selling verticals) and **option buying** (long CE/PE). Rendered as a static, dark, editorial SPA.

## Architecture (frontend)
Vanilla JS, **no build step**. `index.html` loads `assets/js/app.js` (ES modules) + `assets/app.css`; Chart.js + adapters via CDN. Hash router (`assets/js/router.js`), `#app` mount.

### Routes (`app.js`)
| Route | View | In topnav |
|---|---|---|
| `#/` | `views/today.js` — home desk: live book first, then movers boards (embeds `movers.js`) | Today |
| `#/compare` | `views/compare.js` | Compare |
| `#/studio` | `views/studio.js` → Charts + Portfolio sub-tabs | Studio |
| `#/playbook` | `views/playbook.js` → Guide + Regime sub-tabs | Playbook |
| `#/today` | no registered route in `app.js`; the Today desk is `#/` (`views/today.js`) — listed for completeness | (use `#/`) |
| `#/movers` | `views/movers.js` — daily EOD 1-Month movers + Your Book (route currently redirects to `#/`, where the boards render) | Movers |
| `#/selector` | `views/selector.js` — daily deploy/copy/drop selector: today's regime, shortlists, full sortable board, per-algo regime heatmap | Selector |
| `#/algo/:id` | `views/algo.js` — per-algo deep dive | (deep-link) |
| `#/book` | `views/book.js` — 1Y ₹5L-per-name backtest of the live+parked Stratzy book (≤4 lots, per-leg Dhan charges, trailing 365d to generation date) | Book |
| `#/algos` | `views/algos.js` → Rankings + Universe sub-tabs | Algos |

Compat shim routes (redirect only, no view): `#/universe #/charts #/portfolio #/guide #/regime`. Sub-tabs are hosted by `assets/js/subnav.js` via `?sub=` (+ `?tab=`).

### Modules (`assets/js/`)
- `data.js` — cached JSON loader: `load(name)` fetches `./<name>.json` once; `loadMany`, `boot()` (preloads explore_data + equity_curves + stratzy_headlines).
- `store.js` — shared param store (period / returns gross-net / category / search) with localStorage + pub/sub for cross-filtering; fee constants.
- `router.js` — tiny hash router with `:param`, topnav active-state.
- `components.js` — shared UI: `sectionHead`, `controlRail`, `scorecard`, `bookTag`, `styleTag`, `openDrawer`.
- `util.js` — formatters (`fmtInr`/`fmtLakh`/`fmtPts`/`fmtPct`/`fmtNum`/`fmtDate`, Indian digit grouping), `pnlClass`, `escapeHtml`, `debounce`, `sparkSVG`/`dualSparkSVG`, `heatCell`, `maxDrawdown`.
- `cmdk.js` — ⌘K command palette (provider built in `app.js` `buildCommands`).
- `chartdd.js` — drawdown ("underwater") shading + Chart.js band plugin.
- `regime.js` — Nifty market-regime classifier (direction × realized-vol terciles). **NB: a second `regime.js` exists as a view under `views/` — naming footgun.**
- `subnav.js` — sub-tab host (mount/teardown children under `?sub=`).
- `views/` — `algos, rankings, universe, compare, studio, charts, portfolio, playbook, guide, regime, algo, movers, selector`.

## Data files
**Fetched by the SPA at runtime (12 + movers):** `explore_data`, `equity_curves`, `stratzy_headlines` (boot); then lazily `report_data`, `diff_data`, `explore_diff`, `option_buying_diff`, `option_buying_strategy_guide`, `option_buying_stratzy`, `nifty_daily`, `correlations`, `universe`; plus `movers/latest.json` for the Movers tab.

**Selector page data (lazy, `#/selector`):** `selector.json` (deploy/copy/drop shortlists + all 118 in-scope algos' metrics, today's regime, and per-algo PASS/FAIL eligibility reasons — built by `generate_selector.py`) and, only when a row is expanded, `regime_panel.json` (283KB, per-algo P&L broken out by trend/VIX/IV-rank/skew/DTE bucket, from `regime_study.py` — the source for the per-algo regime heatmap). Upstream market-context files these depend on: `nifty_vix_daily.json` (502d NIFTY OHLC + India VIX + trend/RV, from `fetch_market_data.py`) and `iv_daily.json` (245d bhavcopy ATM/OTM IV + skew + IV-rank, from `fetch_bhavcopy.py`, lagged ~1 trading day to publish).

**Intermediate / not fetched:** `option_buying_analysis.json` (5.6MB, feeds 4 generators), `option_buying_report_data.json`, `option_buying_calendar_2026.json`, `calendar_2026.json`, `trade_examples.json`, `data/advices/` (scrape cache), `data/trades_enriched.parquet` (from `regime_study.py`, correlation fallback source). The two big legacy files are in `.vercelignore`.

## Data source & auth
Raw data = the live **Stratzy.in REST API**.
- **Public (no auth):** `GET /api/web/algo/list` (148 algos + all headline metrics incl. `oneMonthPnl`, `sevenDayPnl`, `rollingReturns30Day`), `GET /api/strategies`.
- **Auth-gated (the deep per-trade source):** `GET /api/web/pastAdvices?advisorId={id}&date=YYYY-MM-DD` — needs a logged-in local **Chrome session (DHAN broker)**. Cookies are exported to `/tmp` and driven by Playwright (`fetch_option_buying.mjs`, run **from `/tmp`**). Cookie/session files live only in `/tmp` and are **never committed** (see `.gitignore`).
- `generate_ob_strategy_guide.py` also pulls `^NSEI` from Yahoo Finance (yfinance).

## Regeneration pipeline (11 steps)
Full detail + gotchas in `~/stratzy-archive/REGENERATION_RUNBOOK.md`. Order:
1. `fetch_option_buying.mjs` (from `/tmp`) → raw `/tmp/all_*.json`
2. `generate_report.py` → `report_data.json`
3. `generate_diff_data.py` → `diff_data.json`
4. `analyze_option_buying.py` → `option_buying_analysis.json` (+ report_data, + calendar_2026)
5. `generate_option_buying_diff.py` → `option_buying_diff.json`
6. `generate_ob_strategy_guide.py` → `option_buying_strategy_guide.json`, `nifty_daily.json`
7. `generate_ob_stratzy_data.py` → `option_buying_stratzy.json`
8. `generate_equity_curves.py` → `equity_curves.json`
9. `generate_explore_data.py` → `explore_data.json`, `explore_diff.json`, `stratzy_headlines.json`
10. `generate_correlations.py` → `correlations.json`
11. `generate_universe.py` → `universe.json`

## Selector pipeline (`#/selector`, separate adapter — not the 11-step pipeline above)
Reads the `data/advices/` scrape cache (`data/algo_list.json` metadata, incl. `category`/`marginRequired`) via `build_raw_from_cache.py`, not the `/tmp`-shaped Playwright dump. Order:
1. `scrape_all_algos.py` → `data/advices/<advisorId>/<date>.json` (1Y pastAdvices, resumable; needs `data/stratzy_cookies.json`, gitignored)
2. `fetch_market_data.py` → `nifty_vix_daily.json` (public, yfinance)
3. `fetch_bhavcopy.py` → `iv_daily.json` (public, NSE bhavcopy; lags ~1 trading day)
4. `regime_study.py` → `regime_panel.json` + `data/trades_enriched.parquet` (joins every closed advice to market context as-of-entry)
5. `generate_selector.py` → `selector.json` (deploy/copy/drop shortlists + eligibility reasons; also reads `correlations.json`, `explore_data.json`, `portfolio.json`)
Dhan intraday (`fetch_dhan_intraday.py` → `data/dhan/*.csv`, 5-min NIFTY + rolling weekly options) is **manual, not wired into any refresh script** — it's a standalone fetch run by hand when fresher intraday context is needed.
Wired into `scripts/refresh_weekly.sh` (steps 1–5 above run right after the deep pipeline, before AI regen); no daily wiring.

**Movers feature (public API only, no Chrome auth):** `generate_movers.py` → `movers/snapshots/YYYY-MM-DD.json` + `movers/latest.json`. Reads `portfolio.json` (ck's holdings) + `explore_data.json` (research-universe flag). 1-Day/1-Week/1-Month boards + portfolio `ai_insight`. Also on `#/movers`: a **regime-now banner** (current Nifty regime via `regime.js` + which book algos historically fit it, from `algo_insights.json`).

**Per-algo AI insight (NEW):** plain-English research profile on every deep-algo deep-dive (`#/algo/:id`) — what it trades, put/call bias, style (premium-selling/mean-revert vs trend/momentum), expiry (soft), hold (qualitative), frequency, win/loss + profit factor, when it makes money (bull/side/bear regime), vol sensitivity (realized-vol proxy — NO implied-vol data exists), and 5 similar / 5 opposite algos (from `correlations.json`). Pipeline (all local; deep data needs DHAN Chrome login):
1. `generate_algo_facts.py` → `insights/_facts.json` + per-algo `insights/facts/<id>.json` + `insights/_index.json` (regime buckets are a faithful port of `regime.js`; neighbours from `correlations.json`).
2. Workflow `workflows/algo-insights.mjs` (Claude fan-out: generate → adversarial verify) → per-algo judgment fields. Capture with `capture_insights.py <transcript_dir>` → `insights/_judgments.json`.
3. `merge_algo_insights.py` merges judgment + deterministic numbers → **`algo_insights.json`** (repo root, served). `bias` is computed deterministically here, never by the LLM.
Screener: `#/` Universe tab gains AI **style/bias** filters (from `algo_insights.json`).

**Automation — local launchd loop (`scripts/`):** a headless cloud loop is IMPOSSIBLE (the deep pipeline's `pastAdvices` source needs a live DHAN Chrome cookie jar on this Mac). So:
- `scripts/refresh_daily.sh` (launchd `com.ck.stratzy-daily`, weekdays 18:30 IST): public-API only — `generate_movers.py` + `generate_universe.py` → commit → deploy → optional @pookie digest. No auth.
- `scripts/refresh_weekly.sh` (launchd `com.ck.stratzy-weekly`, Sun 10:00 IST): full deep pipeline (needs DHAN login) + `generate_algo_facts.py` + AI regen (drives the workflow via `claude -p`) + `merge_algo_insights.py` → deploy. Fails-soft if the DHAN session is dead. Deep-pipeline fetch lives in a `scripts/run_deep.sh` you maintain (exact fetch invocation per `~/stratzy-archive/REGENERATION_RUNBOOK.md`).
- Install: `cp scripts/launchd/*.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.ck.stratzy-*.plist`.
- **Cadence rule:** daily = numbers only; ALL AI (per-algo profiles + movers portfolio insight) = weekly + one-time.

## Deploy
```bash
cd ~/stratzy-credit-spread-report
vercel --prod --yes          # project linked via .vercel/ (team 5908 = team_QUgI2tENi0Wo8L7m2s2GoATi)
```
- `.vercelignore` strips `*.py`, `*.mjs`, `legacy/`, and the two heavy intermediate JSONs from the deploy bundle. `movers/*.json` **is** deployed.
- `*.json` served `Cache-Control: max-age=0, must-revalidate` (via `vercel.json`) → a redeploy refreshes data instantly.
- Vercel **git auto-deploy is flaky** for ck-delta projects — explicit `vercel --prod --yes` is the reliable path.
- `serve.py` runs a local http server on :8765 for offline dev.

## Known issues (documented, not yet fixed)
- **Dead redirect:** `vercel.json` `/option-buying-portfolio → /#/charts?tab=portfolio` — portfolio is now a Studio sub-tab (`sub=portfolio`), not a Charts tab. Lands on Charts.
- **Unused preload:** `data.js boot()` fetches `stratzy_headlines.json` but no view reads it.
- **Candidate dead exports** in `data.js`: `curveFor`, `edition`, `peek`.
- **Stale runbook note:** `REGENERATION_RUNBOOK.md §7` claims a move to Vercel team **1648** / alias `pq4709-perf` — superseded. Current is team **5908** / `stratzy-credit-spread-report.vercel.app`.

## Relationship to the archives
- **`~/stratzy-archive/`** — a 2026-06-24 regeneration toolkit + verified snapshot: `pipelines/` (generators), `fetch/`, `pages/` (the 10 pre-SPA HTML pages), `data/` (byte-identical JSON copies), `REGENERATION_RUNBOOK.md`, and dated live API probes (`probes_live_2026-06-24/`). Not a newer code version — a documented backup/how-to-rebuild.
- **`~/STRATZY_COMPLETE_ARCHIVE.md`** — a 34KB self-contained reconstruction narrative (findings, architecture, parity caveats). Key caveat: high all-time points ≠ currently profitable (Stratzy's trailing-1Y% and recomputed all-time points rank algos very differently).
- **`legacy/`** (this repo) — the original 10 multi-page HTML build, superseded by the SPA on 2026-06-24 (kept for history; `.vercelignore`d).
