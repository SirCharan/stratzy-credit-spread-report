// algo.js — per-algo deep dive (folds option-buying-algo + a CS detail).
// Route: #/algo/:id . OB algos use option_buying_stratzy.json; CS use report_data + equity_curves.

import { load } from '../data.js';
import { scorecard, bookTag, styleTag } from '../components.js';
import { fmtPts, fmtLakh, fmtInr, fmtPct, fmtNum, fmtDate, pnlClass, escapeHtml, sparkSVG } from '../util.js';
import { buildNiftyRegime, attributeStrategy, tradeStats } from '../regime.js';
import { ddBandPlugin, underwaterRanges } from '../chartdd.js';

const GRID = '#2b261e', TICK = '#8A8070';
let charts = [];

function killCharts() { charts.forEach(c => { try { c.destroy(); } catch {} }); charts = []; }

// ---- shared regime attribution panel (Almanac-computed, realized) ----
function regimeCells(buckets, keys, labels) {
  return keys.map((k, i) => { const r = buckets[k] || {}; return `<div style="flex:1;text-align:center;padding:8px;border-radius:8px;background:var(--surface-2)">
    <div class="muted" style="font-size:.66rem;text-transform:uppercase;letter-spacing:.08em">${labels[i]}</div>
    <div class="mono ${pnlClass(r.avg_pts)}" style="font-size:1rem;margin-top:4px">${r.trades ? fmtPts(r.avg_pts) : '—'}</div>
    <div class="muted" style="font-size:.66rem">${fmtNum(r.trades)} trades · ${r.trades ? fmtPct(r.win_rate) : '—'} WR</div></div>`; }).join('');
}
function regimePanel(attr) {
  return `<div class="card" style="margin-top:22px"><div class="card-head"><h3>When it makes money</h3><span class="sub">Almanac · realized, by Nifty regime at trade exit</span></div>
    <div class="card-pad">
      <div class="eyebrow" style="margin-bottom:8px">Market direction · avg pts / trade</div>
      <div style="display:flex;gap:8px;margin-bottom:16px">${regimeCells(attr.dir, ['bull', 'sideways', 'bear'], ['Bull', 'Sideways', 'Bear'])}</div>
      <div class="eyebrow" style="margin-bottom:8px">Volatility (realized) · avg pts / trade</div>
      <div style="display:flex;gap:8px">${regimeCells(attr.vol, ['low', 'normal', 'high'], ['Low vol', 'Normal', 'High vol'])}</div>
      <p class="muted" style="font-size:.72rem;margin-top:12px">Direction = trailing 20-day Nifty move (≥+2% bull / ≤−2% bear); volatility = trailing 20-day realized vol split into terciles. Each trade is tagged by the regime on its exit date.</p>
    </div></div>`;
}
// ---- AI profile card (from algo_insights.json; research aid, not advice) ----
function aiStat(label, val) {
  return `<div style="text-align:center;padding:8px 12px;border-radius:8px;background:var(--surface-2);min-width:76px">
    <div class="muted" style="font-size:.62rem;text-transform:uppercase;letter-spacing:.06em">${label}</div>
    <div class="mono" style="font-size:.92rem;margin-top:3px">${val}</div></div>`;
}
function aiChip(label, val) {
  return val ? `<span class="tag tag-muted" style="font-size:.72rem">${escapeHtml(label)} · <b style="color:var(--ink)">${escapeHtml(val)}</b></span>` : '';
}
function neighbourCol(title, arr) {
  if (!arr || !arr.length) return '';
  return `<div style="flex:1;min-width:190px"><div class="eyebrow" style="font-size:.64rem;margin-bottom:6px">${title}</div>
    <ul style="list-style:none;margin:0;padding:0;font-size:.82rem;display:flex;flex-direction:column;gap:5px">
    ${arr.map(n => `<li style="display:flex;justify-content:space-between;gap:10px"><a href="#/algo/${encodeURIComponent(n.id)}">${escapeHtml(n.name)}</a><span class="muted mono" style="font-size:.7rem">r ${n.corr != null ? n.corr.toFixed(2) : '—'}</span></li>`).join('')}</ul></div>`;
}
function aiProfileCard(p) {
  if (!p) return '';
  const wl = p.win_loss || {};
  const pf = wl.profit_factor_inf ? '∞' : (wl.profit_factor != null ? wl.profit_factor.toFixed(2) : '—');
  const row = (k, v, cls = '') => v ? `<tr><td class="muted" style="width:148px;vertical-align:top">${k}</td><td class="${cls}">${escapeHtml(v)}</td></tr>` : '';
  return `<div class="card" style="margin:18px 0;padding:20px 22px;border-left:3px solid var(--gold)">
    <div class="eyebrow" style="margin-bottom:10px">AI profile <span class="muted" style="text-transform:none;font-family:var(--mono);font-size:.64rem">· research aid, not advice</span></div>
    ${p.summary ? `<p style="font-size:.95rem;color:var(--ink);margin:0 0 14px;max-width:74ch">${escapeHtml(p.summary)}</p>` : ''}
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px">
      ${aiChip('Bias', p.bias)}${aiChip('Style', p.style)}${aiChip('Expiry', p.expiry)}${aiChip('Hold', p.hold)}
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
      ${aiStat('Trades/mo', p.frequency_per_month != null ? fmtNum(p.frequency_per_month, 1) : '—')}
      ${aiStat('Win rate', fmtPct(wl.win_rate))}
      ${aiStat('Avg win', fmtPts(wl.avg_win_pts, false))}
      ${aiStat('Avg loss', fmtPts(wl.avg_loss_pts, false))}
      ${aiStat('Profit factor', pf)}
    </div>
    <table class="data" style="font-size:.84rem;margin-bottom:4px"><tbody>
      ${row('What it trades', p.what_it_trades)}
      ${row('Makes money when', p.makes_money_when)}
      ${row('Vol sensitivity', p.iv_sensitivity)}
      ${row('Why this style', p.style_evidence, 'muted')}
    </tbody></table>
    ${(p.similar && p.similar.length) || (p.opposite && p.opposite.length) ? `<div style="display:flex;gap:22px;flex-wrap:wrap;margin-top:14px">
      ${neighbourCol('Most similar', p.similar)}${neighbourCol('Most opposite', p.opposite)}</div>` : ''}
  </div>`;
}

// underwater ranges of a plotted [{x,y}] cumulative series, as an always-on band plugin
function ddBandFor(series) { const r = underwaterRanges(series); return ddBandPlugin(() => r, () => true); }

export async function render(root, params) {
  const id = params.id;
  const [ob, equity, nifty, insights] = await Promise.all([
    load('option_buying_stratzy').catch(() => null),
    load('equity_curves').catch(() => null),
    load('nifty_daily').catch(() => null),
    load('algo_insights').catch(() => null),
  ]);
  const profile = insights && insights.algos ? insights.algos[id] : null;
  const regime = nifty ? buildNiftyRegime(nifty) : null;
  const obAlgo = ob && ob.algos.find(a => a.id === id);
  if (obAlgo) return renderOB(root, obAlgo, equity, regime, profile);

  const [report, explore] = await Promise.all([
    load('report_data').catch(() => null), load('explore_data').catch(() => null),
  ]);
  const csAlgo = report && report.algos.find(a => a.id === id);
  if (csAlgo) return renderCS(root, csAlgo, equity, regime, profile);

  const uni = await load('universe').catch(() => null);
  const u = uni && (uni.algos || []).find(a => a.id === id);
  const ex = explore && explore.algos.find(a => a.id === id);
  const head = ex || u;
  if (head) {
    const oneM = u && u.ret_1m, oneY = u && u.ret_1y, threeM = u && u.ret_3m;
    root.innerHTML = basicHeader(head) + `
      ${scorecard([
        { label: 'Stratzy 1M', value: fmtPct(oneM), sm: true, cls: pnlClass(oneM) },
        { label: 'Stratzy 3M', value: fmtPct(threeM), sm: true, cls: pnlClass(threeM) },
        { label: 'Stratzy 1Y', value: fmtPct(oneY), sm: true, cls: pnlClass(oneY) },
      ])}
      <div class="note" style="margin-top:16px">No fill recompute for this algo — Stratzy headline % only.
        Deep points/₹ per lot exist for the credit-spread and option-buying research set.
        <a href="#/algos">Back to rankings →</a></div>`;
    return;
  }
  root.innerHTML = `<div class="note">Unknown algo. <a href="#/">Back to Today →</a></div>`;
}

function backLink() { return `<a href="#/algos" class="btn ghost" style="margin-bottom:16px">← All algos</a>`; }

function basicHeader(a) {
  return `<div class="fade-in">${backLink()}
    <div class="eyebrow" style="margin-bottom:8px">${a.category === 'credit_spread' ? 'Credit spread' : 'Option buying'} · ${escapeHtml(a.underlying || '')}</div>
    <h1 class="section-title">${escapeHtml(a.name)}</h1>
    ${a.one_liner ? `<p class="section-intro">${escapeHtml(a.one_liner)}</p>` : ''}</div>`;
}

/* ===================== OPTION BUYING ===================== */
function renderOB(root, a, equity, niftyRegime, profile) {
  killCharts();
  const st = { basis: 'min', period: 'MAX' };
  const h = a.stratzy_headline || {};
  const sumAll = a.summary.all || {}, sum26 = a.summary.ytd_2026 || {};
  const strat = a.strategy || {};
  const eqAlgo = equity && equity.algos.find(z => z.id === a.id);
  const attr = (niftyRegime && eqAlgo) ? attributeStrategy((eqAlgo.curves || {}).trade_pts, niftyRegime) : null;

  root.innerHTML = `<div class="fade-in">
    ${backLink()}
    <div class="eyebrow" style="margin-bottom:8px">Option buying · ${escapeHtml(a.underlying || 'NIFTY')} · ${escapeHtml(a.risk || '')} risk · live ${fmtDate(a.live_since)}</div>
    <h1 class="section-title" style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">${escapeHtml(a.name)} ${strat.family_title ? `<span class="tag tag-ob">${escapeHtml(strat.family_title)}</span>` : ''}</h1>
    <div style="margin:18px 0">${scorecard([
      { label: '2026 YTD pts', value: fmtPts(a.summary.ytd_pts ?? sum26.total_points), sm: true, cls: pnlClass(a.summary.ytd_pts ?? sum26.total_points) },
      { label: 'All-time pts', value: fmtPts(sumAll.total_points), sm: true, cls: pnlClass(sumAll.total_points) },
      { label: 'Win rate (all)', value: fmtPct(sumAll.win_rate), sm: true },
      { label: 'Stratzy 1Y', value: fmtPct(h.one_year_pnl_pct), sm: true, cls: pnlClass(h.one_year_pnl_pct) },
      { label: 'Max drawdown', value: fmtLakh(a.performance.max_dd_inr), sm: true, cls: 'neg' },
    ])}</div>
    ${aiProfileCard(profile)}

    <div class="controls" style="margin-bottom:10px">
      <div class="seg" id="ob-basis"><span class="seg-label">Basis</span><button data-b="min">At min capital</button><button data-b="max">Stratzy chart base</button></div>
      <div class="seg" id="ob-period"><span class="seg-label">Window</span>${['1M','3M','6M','1Y','MAX'].map(p=>`<button data-p="${p}">${p}</button>`).join('')}</div>
    </div>
    <div class="chart-frame"><div class="chart-canvas-wrap" style="height:380px"><canvas id="ob-eq"></canvas></div>
      <div style="height:120px;margin-top:8px"><canvas id="ob-tl"></canvas></div></div>

    <div class="grid grid-2" style="margin-top:22px">
      <div class="card"><div class="card-head"><h3>The setup</h3><span class="sub">inferred, not Stratzy's labels</span></div>
        <div class="card-pad" id="ob-strategy"></div></div>
      <div class="card"><div class="card-head"><h3>Capital & lots</h3></div><div class="card-pad" id="ob-stats"></div></div>
    </div>

    <div class="section" style="margin-top:28px">
      <div class="eyebrow" style="margin-bottom:12px">Signal log · ${fmtNum((a.trades||[]).length)} trades</div>
      <div class="table-wrap" style="max-height:520px;overflow:auto"><table class="data"><thead><tr>
        <th>Date</th><th>Side</th><th class="num">Lots</th><th class="num">Max</th><th class="num">Size</th><th class="num">Margin</th><th class="num">Cap %</th><th class="num">Day %</th><th class="num">Pts</th>
      </tr></thead><tbody>${(a.trades||[]).slice().reverse().map(t=>`<tr>
        <td class="mono" style="font-size:.74rem">${fmtDate(t.date)}</td>
        <td><span class="tag ${t.side==='CE'?'tag-nifty':'tag-sensex'}">${escapeHtml(t.side||'')}</span></td>
        <td class="num">${fmtNum(t.lots_traded)}</td><td class="num muted">${fmtNum(t.max_lots)}</td>
        <td class="num muted">${fmtNum(t.lot_size)}</td><td class="num">${fmtLakh(t.margin)}</td>
        <td class="num muted">${fmtPct(t.capital_pct,0)}</td><td class="num ${pnlClass(t.day_pct)}">${fmtPct(t.day_pct)}</td>
        <td class="num ${pnlClass(t.points)}">${fmtPts(t.points)}</td></tr>`).join('')}</tbody></table></div>
    </div>
  </div>`;

  // strategy panel
  const regime = strat.regime || {};
  const regCell = (k, lbl) => { const r = regime[k] || {}; return `<div style="flex:1;text-align:center;padding:8px;border-radius:8px;background:var(--surface-2)">
    <div class="muted" style="font-size:.66rem;text-transform:uppercase;letter-spacing:.08em">${lbl}</div>
    <div class="mono ${pnlClass(r.avg_pts)}" style="font-size:1rem;margin-top:4px">${fmtPts(r.avg_pts)}</div>
    <div class="muted" style="font-size:.66rem">${fmtNum(r.trades)} trades</div></div>`; };
  root.querySelector('#ob-strategy').innerHTML = `
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
      ${strat.trend_label?`<span class="tag tag-muted">${escapeHtml(strat.trend_label.replace(/_/g,' '))}</span>`:''}
      ${strat.market_fit?`<span class="tag tag-muted">${escapeHtml(strat.market_fit.replace(/_/g,' '))}</span>`:''}
      ${strat.dominant_moneyness?`<span class="tag tag-muted">${escapeHtml(strat.dominant_moneyness)}</span>`:''}
      ${strat.inactive_2026?`<span class="tag tag-thin">inactive 2026</span>`:''}
    </div>
    <div class="wlbar" style="width:100%;margin-bottom:6px"><i class="w" style="width:${strat.ce_pct||0}%;background:#6FB4F2"></i><i class="l" style="width:${strat.pe_pct||0}%;background:#E8A33D"></i></div>
    <div class="muted" style="font-size:.72rem;margin-bottom:14px">CE ${fmtPct(strat.ce_pct,0)} · PE ${fmtPct(strat.pe_pct,0)} · ${fmtNum(strat.trades_per_month)}/mo · ${escapeHtml(strat.avg_frequency||'')}</div>
    <div style="display:flex;gap:8px;margin-bottom:14px">${regCell('bull','Bull')}${regCell('sideways','Side')}${regCell('bear','Bear')}</div>
    ${attr ? `<div class="eyebrow" style="margin:4px 0 6px;font-size:.66rem">By realized volatility · avg pts / trade</div>
      <div style="display:flex;gap:8px;margin-bottom:14px">${regimeCells(attr.vol, ['low', 'normal', 'high'], ['Low vol', 'Normal', 'High vol'])}</div>` : ''}
    ${(strat.bullets||[]).length?`<ul style="margin-left:18px;font-size:.84rem;color:var(--ink-2);display:flex;flex-direction:column;gap:6px">${strat.bullets.map(b=>`<li>${escapeHtml(b)}</li>`).join('')}</ul>`:''}`;

  // capital/lots panel
  const cap = a.capital || {}, lots = a.lots || {};
  const kv = (k,v)=>`<tr><td class="muted">${k}</td><td class="num" style="text-align:right">${v}</td></tr>`;
  root.querySelector('#ob-stats').innerHTML = `<table class="data" style="font-size:.8rem"><tbody>
    ${kv('Min capital', fmtInr(cap.minimum))}${kv('Avg capital', fmtInr(cap.average))}${kv('Stratzy chart base', fmtInr(cap.chart_base))}
    ${kv('Avg lots / trade', fmtNum(lots.avg_lots_traded,1))}${kv('Max lots seen', fmtNum(lots.max_lots_seen))}${kv('Lot size', (lots.lot_sizes_seen||[lots.lot_size]).join(', '))}
    ${kv('Avg margin / trade', fmtInr(lots.avg_margin))}${kv('Avg cap % / trade', fmtPct(lots.avg_capital_pct_per_trade,0))}
    ${kv('Stratzy past return', fmtPct(h.past_return_pct))}${kv('Stratzy win ratio', fmtPct(h.win_ratio))}${kv('Stratzy max DD', fmtPct(h.max_drawdown_pct||h.drawdown_pct))}
  </tbody></table>`;

  const drawCharts = () => {
    killCharts();
    const basisArr = st.basis === 'min' ? (a.performance.equity_min_inr || a.performance.equity_inr) : a.performance.equity_inr;
    const eq = sliceByPeriod(basisArr, st.period);
    const tl = sliceByPeriod(a.performance.timeline_pct || [], st.period);
    const eqc = document.getElementById('ob-eq');
    const eqSeries = eq.map(p => ({ x: p.x, y: p.y }));
    charts.push(new Chart(eqc, { type: 'line', data: { datasets: [{
      label: 'Equity', data: eqSeries,
      borderColor: '#E8A33D', backgroundColor: 'rgba(232,163,61,0.10)', borderWidth: 2.2, fill: true, pointRadius: 0, tension: 0.06,
    }] }, plugins: [ddBandFor(eqSeries)], options: lineOpts(true) }));
    const tlc = document.getElementById('ob-tl');
    charts.push(new Chart(tlc, { type: 'bar', data: { datasets: [{
      label: 'Day %', data: tl.map(p => ({ x: p.x, y: p.y })),
      backgroundColor: tl.map(p => p.y >= 0 ? '#46C68C' : '#F2615C'), borderWidth: 0,
    }] }, options: barOpts() }));
  };
  root.querySelector('#ob-basis').addEventListener('click', e => { const b=e.target.closest('button'); if(b){st.basis=b.dataset.b; syncSeg(root,'#ob-basis','b',st.basis); drawCharts();} });
  root.querySelector('#ob-period').addEventListener('click', e => { const b=e.target.closest('button'); if(b){st.period=b.dataset.p; syncSeg(root,'#ob-period','p',st.period); drawCharts();} });
  syncSeg(root,'#ob-basis','b',st.basis); syncSeg(root,'#ob-period','p',st.period);
  drawCharts();
  return killCharts;
}

/* ===================== CREDIT SPREAD ===================== */
function renderCS(root, a, equity, niftyRegime, profile) {
  killCharts();
  const at = a.all_time || {}, y26 = a.ytd_2026 || {}, ts = a.trade_structure || {};
  const st = { period: '2026', ymode: 'pts' };
  const eqAlgo = equity && equity.algos.find(z => z.id === a.id);
  const attr = (niftyRegime && eqAlgo) ? attributeStrategy((eqAlgo.curves || {}).trade_pts, niftyRegime) : null;
  const pf = eqAlgo ? tradeStats((eqAlgo.curves || {}).trade_pts).profitFactor : null;

  root.innerHTML = `<div class="fade-in">
    ${backLink()}
    <div class="eyebrow" style="margin-bottom:8px">Credit spread · ${escapeHtml(a.underlying||'NIFTY')} · lot ${a.lot_size} · live ${fmtDate(a.live_since)}</div>
    <h1 class="section-title" style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">${escapeHtml(a.name)} ${styleTag(a.style, a.style_label)}</h1>
    <div style="margin:18px 0">${scorecard([
      { label: '2026 YTD pts', value: fmtPts(y26.net_points), sm: true, cls: pnlClass(y26.net_points) },
      { label: 'All-time pts', value: fmtPts(at.net_points), sm: true, cls: pnlClass(at.net_points) },
      { label: '₹ / lot (all)', value: fmtLakh(at.net_inr), sm: true },
      { label: 'Win rate (all)', value: fmtPct(at.win_rate), sm: true },
      { label: 'Profit factor', value: pf == null ? '—' : (pf === Infinity ? '∞' : pf.toFixed(2)), sm: true, cls: pf != null && pf >= 1 ? 'pos' : 'neg' },
      { label: 'Max DD', value: fmtPts(at.max_drawdown_pts, false), sm: true, cls: 'neg' },
    ])}</div>
    ${aiProfileCard(profile)}

    <div class="controls" style="margin-bottom:10px">
      <div class="seg" id="cs-period"><span class="seg-label">Period</span><button data-p="2026">2026</button><button data-p="all">All-time</button></div>
      <div class="seg" id="cs-y"><span class="seg-label">Y</span><button data-y="pts">Points</button><button data-y="inr">₹ / lot</button></div>
    </div>
    <div class="chart-frame"><div class="chart-canvas-wrap" style="height:420px"><canvas id="cs-eq"></canvas></div></div>
    ${attr ? regimePanel(attr) : ''}

    <div class="grid grid-2" style="margin-top:22px">
      <div class="card"><div class="card-head"><h3>Trade structure</h3></div><div class="card-pad"><table class="data" style="font-size:.8rem"><tbody>
        ${kvRow('Spread type', ts.spread_type || '—')}
        ${kvRow('Avg strike width', ts.avg_strike_width != null ? fmtNum(ts.avg_strike_width) : '—')}
        ${kvRow('Avg entry credit', ts.avg_entry_credit_pts != null ? fmtPts(ts.avg_entry_credit_pts, false) + ' pts' : '—')}
        ${kvRow('Side mix', ts.side_summary || `CE ${fmtPct(ts.ce_only_pct,0)} / PE ${fmtPct(ts.pe_only_pct,0)} / both ${fmtPct(ts.both_pct,0)}`)}
        ${kvRow('Iron-condor trades', ts.iron_condor_trades != null ? `${fmtNum(ts.iron_condor_trades)} (${fmtPct(ts.iron_condor_pct,0)})` : '—')}
        ${kvRow('Avg margin', at.avg_margin != null ? fmtInr(at.avg_margin) : '—')}
      </tbody></table></div></div>
      <div class="card"><div class="card-head"><h3>Performance split</h3></div><div class="card-pad"><table class="data" style="font-size:.8rem"><tbody>
        ${kvRow('2026 trades', fmtNum(y26.trades))}
        ${kvRow('2026 win rate', fmtPct(y26.win_rate))}
        ${kvRow('2026 avg win / loss', `${fmtPts(y26.avg_win_pts,false)} / ${fmtPts(y26.avg_loss_pts,false)}`)}
        ${kvRow('All-time trades', fmtNum(at.trades))}
        ${kvRow('All-time avg win / loss', `${fmtPts(at.avg_win_pts,false)} / ${fmtPts(at.avg_loss_pts,false)}`)}
        ${kvRow('Trades / month', fmtNum(at.trades_per_month,1))}
      </tbody></table></div></div>
    </div>
    <div id="cs-monthly" class="section" style="margin-top:26px"></div>
    <div id="cs-examples" class="section"></div>
  </div>`;

  // monthly bars (2026)
  const months = a.monthly_2026 || {};
  const mk = Object.keys(months).filter(k => k.startsWith('2026')).sort();
  if (mk.length) {
    const max = Math.max(...mk.map(k => Math.abs(months[k].pts || 0)), 1);
    root.querySelector('#cs-monthly').innerHTML = `<div class="eyebrow" style="margin-bottom:12px">2026 by month · points</div>
      <div style="display:flex;gap:6px;align-items:flex-end;height:120px">${mk.map(k => { const v = months[k].pts || 0; const hgt = Math.abs(v) / max * 100;
        return `<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px" title="${k}: ${fmtPts(v)}">
          <div style="width:70%;height:${hgt}%;min-height:2px;background:${v>=0?'#46C68C':'#F2615C'};border-radius:3px 3px 0 0"></div>
          <span class="muted" style="font-size:.6rem">${k.slice(5)}</span></div>`; }).join('')}</div>`;
  }

  // trade examples from diff_data
  load('diff_data').then(diff => {
    const ex = diff.examples && diff.examples[a.name];
    if (!ex) return;
    const box = (t, lbl, cls) => t ? `<div class="card card-pad" style="border-left:3px solid var(--${cls})">
      <div class="eyebrow" style="margin-bottom:8px">${lbl} · <span class="${cls==='gain'?'pos':'neg'}">${fmtPts(t.pts)}</span></div>
      ${t.sell?`<div class="mono" style="font-size:.74rem">SELL ${escapeHtml(t.sell.sym||'')} @ ${t.sell.entry}→${t.sell.exit}</div>`:''}
      ${t.buy?`<div class="mono" style="font-size:.74rem">BUY ${escapeHtml(t.buy.sym||'')} @ ${t.buy.entry}→${t.buy.exit}</div>`:''}
      ${t.date?`<div class="muted" style="font-size:.7rem;margin-top:6px">${fmtDate(t.date)}</div>`:''}</div>` : '';
    root.querySelector('#cs-examples').innerHTML = `<div class="eyebrow" style="margin-bottom:12px">Representative trades</div>
      <div class="grid grid-2">${box(ex.best_win,'Best win','gain')}${box(ex.typical_loss,'Typical loss','loss')}</div>`;
  }).catch(()=>{});

  const draw = () => {
    killCharts();
    const root2 = st.period === '2026' ? eqAlgo?.curves_2026 : eqAlgo?.curves;
    const pts = root2 && root2[`daily_${st.ymode}`];
    if (!pts) return;
    const series = pts.map(p => ({ x: p.x, y: p.y }));
    charts.push(new Chart(document.getElementById('cs-eq'), { type: 'line', data: { datasets: [{
      label: a.name, data: series,
      borderColor: '#6FB4F2', backgroundColor: 'rgba(111,180,242,0.10)', borderWidth: 2.2, fill: true, pointRadius: 0, tension: 0.06,
    }] }, plugins: [ddBandFor(series)], options: lineOpts(st.ymode === 'inr') }));
  };
  root.querySelector('#cs-period').addEventListener('click', e => { const b=e.target.closest('button'); if(b){st.period=b.dataset.p; syncSeg(root,'#cs-period','p',st.period); draw();} });
  root.querySelector('#cs-y').addEventListener('click', e => { const b=e.target.closest('button'); if(b){st.ymode=b.dataset.y; syncSeg(root,'#cs-y','y',st.ymode); draw();} });
  syncSeg(root,'#cs-period','p',st.period); syncSeg(root,'#cs-y','y',st.ymode);
  draw();
  return killCharts;
}

/* ===================== shared ===================== */
function kvRow(k, v) { return `<tr><td class="muted">${k}</td><td class="num" style="text-align:right">${v}</td></tr>`; }
const kv = kvRow;
function syncSeg(root, sel, key, val) { [...root.querySelectorAll(sel + ' button')].forEach(b => b.classList.toggle('active', b.dataset[key] === val)); }
function sliceByPeriod(arr, p) {
  if (!arr || !arr.length || p === 'MAX') return arr || [];
  const days = { '1M': 31, '3M': 92, '6M': 183, '1Y': 366 }[p] || 1e5;
  const last = new Date(arr[arr.length - 1].x).getTime();
  const cut = last - days * 864e5;
  return arr.filter(pt => new Date(pt.x).getTime() >= cut);
}
function lineOpts(isInr) {
  return { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
    scales: { x: { type: 'time', time: { tooltipFormat: 'dd MMM yyyy' }, ticks: { color: TICK, maxTicksLimit: 10 }, grid: { color: GRID } },
      y: { ticks: { color: TICK, callback: v => isInr ? '₹' + (v / 1000).toFixed(0) + 'k' : v }, grid: { color: GRID } } },
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: it => (isInr ? '₹' : '') + Math.round(it.parsed.y).toLocaleString('en-IN') } } } };
}
function barOpts() {
  return { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
    scales: { x: { type: 'time', display: false, grid: { display: false } }, y: { ticks: { color: TICK, maxTicksLimit: 4, callback: v => v + '%' }, grid: { color: GRID } } },
    plugins: { legend: { display: false } } };
}
