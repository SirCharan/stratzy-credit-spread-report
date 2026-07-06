# CONTEXT — The Stratzy Almanac

Onboarding doc for this repo. Live: **https://stratzy-credit-spread-report.vercel.app** (Vercel team 5908 / `ck-delta`). Last reconfirmed 2026-07-06.

## What it is
A quant research broadsheet that **reverse-engineers Stratzy.in** (an Indian SEBI algo-advisory marketplace of 148 algos). Rather than trust Stratzy's headline "1-Year Return %", it pulls each algo's per-trade history and **recomputes P&L from raw fills** into the unit a NIFTY trader reads instinctively — **net premium points and ₹ per 1 lot (65 qty)**. Two universes analysed in depth: **credit spreads** (premium-selling verticals) and **option buying** (long CE/PE). Rendered as a static, dark, editorial SPA.

## Architecture (frontend)
Vanilla JS, **no build step**. `index.html` loads `assets/js/app.js` (ES modules) + `assets/app.css`; Chart.js + adapters via CDN. Hash router (`assets/js/router.js`), `#app` mount.

### Routes (`app.js`)
| Route | View | In topnav |
|---|---|---|
| `#/` | `views/algos.js` → Rankings + Universe sub-tabs | Algos |
| `#/compare` | `views/compare.js` | Compare |
| `#/studio` | `views/studio.js` → Charts + Portfolio sub-tabs | Studio |
| `#/playbook` | `views/playbook.js` → Guide + Regime sub-tabs | Playbook |
| `#/movers` | `views/movers.js` — daily EOD 1-Month movers + Your Book | Movers |
| `#/algo/:id` | `views/algo.js` — per-algo deep dive | (deep-link) |

Compat shim routes (redirect only, no view): `#/algos #/universe #/charts #/portfolio #/guide #/regime`. Sub-tabs are hosted by `assets/js/subnav.js` via `?sub=` (+ `?tab=`).

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
- `views/` — `algos, rankings, universe, compare, studio, charts, portfolio, playbook, guide, regime, algo, movers`.

## Data files
**Fetched by the SPA at runtime (12 + movers):** `explore_data`, `equity_curves`, `stratzy_headlines` (boot); then lazily `report_data`, `diff_data`, `explore_diff`, `option_buying_diff`, `option_buying_strategy_guide`, `option_buying_stratzy`, `nifty_daily`, `correlations`, `universe`; plus `movers/latest.json` for the Movers tab.

**Intermediate / not fetched:** `option_buying_analysis.json` (5.6MB, feeds 4 generators), `option_buying_report_data.json`, `option_buying_calendar_2026.json`, `calendar_2026.json`, `trade_examples.json`. The two big files are in `.vercelignore`.

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

**Movers feature (public API only, no Chrome auth):** `generate_movers.py` → `movers/snapshots/YYYY-MM-DD.json` + `movers/latest.json`. Reads `portfolio.json` (ck's holdings) + `explore_data.json` (research-universe flag). Runs daily EOD (weekday) via a Claude scheduled cloud agent; pushes a digest to the @pookie trades bot.

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
