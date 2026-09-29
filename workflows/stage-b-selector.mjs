export const meta = {
  name: 'stratzy-stage-b',
  description: 'Stage B: full deep pipeline, regime study, Opus selector + vault note, #/selector page + deploy',
  phases: [
    { title: 'Pipeline', detail: 'Sonnet: full 121-algo run + parity check' },
    { title: 'Regime', detail: 'Sonnet: regime_study.py -> regime_panel.json, then adversarial verify' },
    { title: 'Select', detail: 'Opus: selector.json + rationale + Obsidian note', model: 'opus' },
    { title: 'UI', detail: 'Sonnet: #/selector view, deploy, live check' },
  ],
}

const REPO = '/Users/ck/stratzy-credit-spread-report'
const COMMON = `
Repo: ${REPO} (vanilla-JS SPA + Python generators; read CONTEXT.md). Scrape cache data/advices/ (121 in-scope algos, 1Y pastAdvices; data/algo_list.json has metadata incl. category, marginRequired lives on each advice). Pipeline adapter: build_raw_from_cache.py + scripts/run_deep_pipeline.sh.
Market data (already built): nifty_vix_daily.json (502d NIFTY OHLC, India VIX, vix_chg_5d, trend_20d bull/side/bear, rv_20d), iv_daily.json (245d bhavcopy ATM IV, put/call 2% OTM IV, skew, iv_rank; fields may be null), data/dhan/nifty_5m.csv (NIFTY 5-min, UTC timestamps), data/dhan/rolling_opt.csv (expired weekly NIFTY options ATM-3..ATM+3 CALL/PUT 5-min with iv/oi/spot; strike column blank — use strike_offset), data/recorder/*.jsonl (recent per-fill context).
Long commands: anything that may run >60s must be started with nohup in the background writing to a log, then polled with short (<=50s) checks that print progress — never one long silent foreground command (the harness kills agents silent for 180s).
Rules: never print cookie/token values. Place no orders. Commit your own work in this repo with a <70-char title + short why body ending "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" (repo has no git remote; do not push). No automatic design-review/quality-gates passes.
`
const RES = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    verification: { type: 'string', description: 'commands + decisive output lines verbatim' },
    gaps: { type: 'array', items: { type: 'string' } },
  },
  required: ['summary', 'files', 'verification', 'gaps'],
}

phase('Pipeline')
// Pipeline already ran (commit "Full-universe deep data"): 118 algos in explore_data.json + insights/_facts.json.
const pipe = args && args.skipPipeline ? { summary: 'Full deep pipeline already ran over 121-algo cache (99.8% coverage); 118 algos packaged in explore_data.json and insights/_facts.json; committed.', files: [], verification: 'explore_data.json 118 algos; insights/_facts.json 118 algos', gaps: ['parity check vs old 50 not run'] } : await agent(`${COMMON}
<task>1. Confirm the scrape finished: tail data/scrape.log must show "DONE coverage" >= 98%. If not, report and stop.
2. Run bash scripts/run_deep_pipeline.sh on the full cache; fix any failures (generate_diff_data.py synthetic iron condor was only tested fail-soft — verify it now works with real data).
3. Parity check: for algos present in git HEAD~2 versions of explore_data.json, compare bull/side/bear regime trade counts from the new insights/_facts.json vs the old — report differences (expected: more trades now, same classification logic). Sanity: spot-check 5 algos' recomputed 1-month P&L direction vs algo/list oneMonthPnl.
4. Commit the regenerated served JSONs + any fixes.</task>`, { label: 'pipeline', phase: 'Pipeline', model: 'sonnet', schema: RES })

phase('Regime')
const regime = await agent(`${COMMON}
Pipeline stage result: ${JSON.stringify(pipe)}
<task>Write regime_study.py -> regime_panel.json (repo root, served). For every closed trade (advice) of every algo: entry timestamp (createdAt, IST), exit, P&L in premium points and Rs per 1 lot, margin, legs (parse NIFTY/BANKNIFTY/SENSEX symbol -> expiry, strike, CE/PE, side), structure (credit spread / strangle / straddle / condor / option buy / other), net side bias (bearish = short calls dominant, bullish = short puts, neutral).
Join market context AS OF ENTRY: trend_20d, VIX level + tercile (1Y), vix_chg_5d sign, iv_rank tercile, skew sign (iv_daily, previous close if same-day not available — no lookahead), DTE bucket (0,1,2,3+), intraday move from open to entry and last-60-min momentum from nifty_5m, ATM IV at entry from rolling_opt (nearest 5-min bar, same expiry week).
Per algo output: {id, name, category, structure, bias, trades, wr, pf, avg_pts, avg_rs, max_dd_rs, calmar, margin_per_lot, cells:{<dimension>:{<bucket>:{n, wr, pf, avg_rs, thin}}}} where thin = n<10. Plus a global block: the same cells aggregated by structure+bias, and "findings" testing: (a) short-call spreads avg % vs short-put spreads avg %, (b) credit-spread loss rate by DTE bucket, (c) momentum-follow share among top-decile algos. State plainly whether each prior finding holds.
Also write data/trades_enriched.parquet (or csv) with every trade + context for later stages.
Commit.</task>`, { label: 'regime-study', phase: 'Regime', model: 'sonnet', schema: RES })

const verify = await agent(`${COMMON}
Regime stage result: ${JSON.stringify(regime)}
<task>Adversarially verify regime_panel.json. Pick 5 algos (2 top, 2 random, 1 option-buying). For each, recompute by hand from raw data/advices files: trade count, win rate, total Rs P&L, and one regime cell (VIX tercile) — check the join has no lookahead (context strictly at/before entry). Check aggregate findings numerically. Report every mismatch with numbers; fix regime_study.py if you find bugs, rerun, commit. Default to skepticism.</task>`, { label: 'regime-verify', phase: 'Regime', model: 'sonnet', schema: RES })

phase('Select')
const select = await agent(`${COMMON}
Regime: ${JSON.stringify(regime)}
Verify: ${JSON.stringify(verify)}
<task>You are the strategist. Build generate_selector.py -> selector.json (repo root) and decide which Stratzy algos ck should DEPLOY (subscribe at 1 lot on Stratzy; auto-executes on his Dhan) and which to COPY (eligible for his 3x sell-leg top-up copier: credit spreads/strangles only; copier adds 3x each SELL leg, max 4 lots, no wing on the extra lots until the 14:50 daily hedge; CE-PE short-lot skew must stay <7; Rs 1L daily kill cap).
Inputs: regime_panel.json, correlations.json, explore_data.json, portfolio.json (ck's current book), today's context = last rows of nifty_vix_daily.json and iv_daily.json.
Criteria (tune only with written justification): DEPLOY trades>=30, PF>=1.15, Calmar>=1.0, positive in >=2 of 3 trend buckets, |corr|<0.6 vs book, margin fits. COPY trades>=60, PF>=1.3, Calmar>=1.5, no trend bucket worse than -0.5x avg, positive in today's VIX tercile and IV-rank tercile, |corr|<0.5 among the copied set, naked-risk check (tail loss of the unhedged 3x sell leg on worst days) within the kill cap.
selector.json: {generated_at, today:{date,trend,vix,vix_tercile,iv_rank,iv_tercile,skew}, rules:{deploy,copy}, algos:[{id,name,category,structure,bias,in_book,metrics:{trades,wr,pf,calmar,max_dd_rs,margin_per_lot,corr_to_book}, fit_today, deploy:{eligible,score,reasons[]}, copy:{eligible,score,reasons[]}, rationale}], shortlist:{deploy:[ids], copy:[ids], drop_from_book:[ids]}}.
Also write a curated Obsidian note /Users/ck/.claude/projects/-Users-ck/memory/stratzy/stratzy-strategy-selector-2026-09.md (v2 frontmatter like sibling notes: name, description, metadata {type: project, tags [project/stratzy, type/research, real-money]}; H1 + status chip; callouts for key findings; sections: method, market-condition findings (what wins in which VIX/IV/trend/DTE), deploy list, copy list, drop list, caveats (survivorship, 1Y only, thin cells); ## Related -> [[_MOC-zerodha-tg-bot]], [[stratzy-almanac-book]], [[topup-sell-leg-copier-v2]], [[stratzy-7algo-reverse-engineer]]; <=6KB) and add one line for it to /Users/ck/.claude/projects/-Users-ck/memory/stratzy/_index-stratzy.md if that file exists (else the folder's _index file).
Commit the repo changes.</task>`, { label: 'selector', phase: 'Select', model: 'opus', schema: RES })

phase('UI')
const ui = await agent(`${COMMON}
Selector: ${JSON.stringify(select)}
<task>Add a #/selector page. Load the 'design' skill first. Follow the site's existing Almanac look: reuse assets/app.css custom properties and assets/js/components.js (sectionHead, scorecard, controlRail), util.js formatters; register the route in assets/js/app.js like the others and add a topnav link "Selector"; add to the cmdk commands. No new hex colors, no system-ui brand font. Sections: today's regime strip (trend, VIX + tercile, IV rank, skew) · Deploy shortlist · Copy shortlist · Drop-from-book · full sortable table with eligibility reasons · per-algo regime heatmap (cells from regime_panel.json, thin cells muted) · "fits today" filter. Mobile-friendly at 375px.
Update CONTEXT.md (routes + new data files + pipeline steps) and scripts/refresh_weekly.sh (add scrape_all_algos.py, fetch_market_data.py, fetch_bhavcopy.py, regime_study.py, generate_selector.py; Dhan intraday stays manual).
Serve locally (python3 serve.py or python3 -m http.server) and check #/selector renders with no console errors via browser-harness (CDP 127.0.0.1:9222). Commit. Deploy: cd ${REPO} && vercel --prod --yes --token=$VERCEL_TOKEN_CKDELTA --scope team_QUgI2tENi0Wo8L7m2s2GoATi (fall back to plain vercel --prod --yes if the token var is unset). Then load https://stratzy-credit-spread-report.vercel.app/#/selector in browser-harness, screenshot desktop and 375px, confirm the algo count and shortlists render.</task>`, { label: 'selector-ui', phase: 'UI', model: 'sonnet', schema: RES })

return { pipe, regime, verify, select, ui }
