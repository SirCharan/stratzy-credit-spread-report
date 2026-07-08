// portfolio.js — correlation matrix, diversifier finder, corr-based builder, portfolio doctor.

import { load } from '../data.js';
import * as router from '../router.js';
import { sectionHead, scorecard, bookTag } from '../components.js';
import { fmtPts, fmtPct, fmtNum, pnlClass, escapeHtml, maxDrawdown } from '../util.js';
import { ddBandPlugin, ddSegment, underwaterRanges } from '../chartdd.js';
import { tradeStats } from '../regime.js';

const GRID = '#2b261e', TICK = '#8A8070';
const IV_IMBALANCE = '687d0a309107a80e07401e5d'; // default holding for the Doctor
// thin overlay palette (warm/editorial, distinct from the bold purple combined line)
const OVERLAY = ['#7FA8C9', '#C99A5B', '#6FB08A', '#C97F9A', '#9A8FD0', '#B0A36A'];

let chart = null, cleanups = [];
let CORR, DAILY, BYID, WR, EQBYID;

function teardown() { if (chart) { chart.destroy(); chart = null; } cleanups.forEach(f => { try { f(); } catch {} }); cleanups = []; }

export async function render(root, params, query) {
  const [corr, eq, explore] = await Promise.all([load('correlations'), load('equity_curves'), load('explore_data')]);
  CORR = corr;
  BYID = new Map(corr.algos.map(a => [a.id, a]));
  WR = new Map((explore.algos || []).map(a => [a.id, a.ytd_2026_wr]));
  EQBYID = new Map(eq.algos.map(a => [a.id, a]));
  // daily day_pnl (points) per algo
  DAILY = new Map();
  for (const a of eq.algos) {
    const pts = (a.curves || {}).daily_pts || [];
    if (pts.length) DAILY.set(a.id, new Map(pts.map(p => [p.x, p.day_pnl || 0])));
  }

  let tab = (query && query.tab) || 'correlation';
  root.innerHTML = `<div class="fade-in">
    ${sectionHead('The portfolio desk', 'Build a book that doesn\'t move as one',
      `Ranking finds winners; this finds <b>diversifiers</b>. Correlation is computed from daily P&L across ${corr.n_algos} recomputed algos — so you can see which strategies actually move independently, blend them, and grade what you already hold.`)}
    <div class="seg" id="p-tabs" style="margin-bottom:20px">
      <span class="seg-label">View</span>
      <button data-tab="correlation">Correlation</button>
      <button data-tab="builder">Builder</button>
      <button data-tab="doctor">Portfolio doctor</button>
    </div>
    <div id="p-body"></div>
  </div>`;

  const tabsEl = root.querySelector('#p-tabs'), body = root.querySelector('#p-body');
  const setTab = t => {
    tab = t;
    [...tabsEl.querySelectorAll('button')].forEach(b => b.classList.toggle('active', b.dataset.tab === t));
    teardown();
    if (t === 'correlation') corrTab(body);
    else if (t === 'builder') builderTab(body, new Set(['687d0a309107a80e07401e5d', '68583ce39edddcb829103b96']));
    else doctorTab(body);
  };
  tabsEl.addEventListener('click', e => { const b = e.target.closest('button[data-tab]'); if (b) setTab(b.dataset.tab); });
  setTab(tab);
  return () => teardown();
}

// ---------- shared engine ----------
function combined(ids) {
  ids = ids.filter(id => DAILY.has(id));
  const cal = new Set();
  ids.forEach(id => DAILY.get(id).forEach((_, d) => cal.add(d)));
  const days = [...cal].sort();
  let cum = 0;
  const series = days.map(d => {
    const day = ids.reduce((s, id) => s + (DAILY.get(id).get(d) || 0), 0);
    cum += day; return { x: d, day, y: cum };
  });
  const daily = series.map(p => p.day);
  const n = daily.length || 1;
  const mean = daily.reduce((s, v) => s + v, 0) / n;
  const sd = Math.sqrt(daily.reduce((s, v) => s + (v - mean) ** 2, 0) / n);
  const sharpe = sd > 0 ? (mean / sd) * Math.sqrt(252) : null;
  return { series, total: cum, maxDD: maxDrawdown(series.map(p => p.y)), sharpe, days: days.length };
}
function soloMaxDD(id) {
  const m = DAILY.get(id); if (!m) return 0;
  const days = [...m.keys()].sort(); let cum = 0; const cs = days.map(d => (cum += m.get(d)));
  return maxDrawdown(cs);
}
// per-strategy cumulative curve + underwater flag per point
function soloSeries(id) {
  const m = DAILY.get(id); if (!m) return { series: [], under: [] };
  const days = [...m.keys()].sort();
  let cum = 0, peak = -Infinity; const series = [], under = [];
  for (const d of days) {
    cum += m.get(d); peak = Math.max(peak, cum);
    series.push({ x: d, y: cum }); under.push(cum < peak - 1e-9);
  }
  return { series, under };
}
// sustained underwater: true on a date once the underwater run is >= 3 consecutive days
function sustainedUnder(id) {
  const m = DAILY.get(id); const out = new Map(); if (!m) return out;
  const days = [...m.keys()].sort();
  let cum = 0, peak = -Infinity, run = 0;
  for (const d of days) {
    cum += m.get(d);
    if (cum < peak - 1e-9) run++; else { run = 0; peak = Math.max(peak, cum); }
    out.set(d, run >= 3);
  }
  return out;
}
// windows where >50% of the selected book is in sustained drawdown
function stressWindows(ids) {
  ids = ids.filter(id => DAILY.has(id));
  if (ids.length < 2) return { stress: new Set(), ranges: [], count: 0 };
  const meta = ids.map(id => ({ u: sustainedUnder(id), first: [...DAILY.get(id).keys()].sort()[0] }));
  const cal = new Set(); ids.forEach(id => DAILY.get(id).forEach((_, d) => cal.add(d)));
  const days = [...cal].sort();
  const stress = new Set();
  for (const d of days) {
    let active = 0, under = 0;
    for (const m of meta) if (d >= m.first) { active++; if (m.u.get(d)) under++; }
    if (active > 0 && under / active > 0.5) stress.add(d);
  }
  // collapse contiguous stress days into [start,end] ranges
  const ranges = []; let rs = null, last = null, li = -2;
  days.forEach((d, i) => {
    if (!stress.has(d)) return;
    if (i !== li + 1) { if (rs) ranges.push([rs, last]); rs = d; }
    last = d; li = i;
  });
  if (rs) ranges.push([rs, last]);
  return { stress, ranges, count: stress.size };
}
// strategies that make money during the current book's stress windows (gap-fillers)
function suggestGapFillers(ids, n = 5) {
  const { stress, count } = stressWindows(ids);
  if (!count) return [];
  const minCov = Math.max(5, Math.ceil(0.3 * count));
  const sel = new Set(ids);
  return CORR.algos
    .filter(a => a.total_pts > 0 && DAILY.has(a.id) && !sel.has(a.id))
    .map(a => {
      const m = DAILY.get(a.id); let sum = 0, cov = 0;
      stress.forEach(d => { if (m.has(d)) { sum += m.get(d); cov++; } });
      return { id: a.id, avg: cov ? sum / cov : -Infinity, coverage: cov };
    })
    .filter(x => x.coverage >= minCov && x.avg > 0)
    .sort((x, y) => y.avg - x.avg)
    .slice(0, n);
}
function pairCorr(a, b) { return (CORR.matrix[a] && CORR.matrix[a][b] != null) ? CORR.matrix[a][b] : null; }
function avgPairCorr(ids) {
  const vs = [];
  for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
    const c = pairCorr(ids[i], ids[j]); if (c != null) vs.push(c);
  }
  return vs.length ? vs.reduce((s, v) => s + v, 0) / vs.length : null;
}
function avgCorrTo(id, set) {
  const vs = set.filter(x => x !== id).map(x => pairCorr(id, x)).filter(c => c != null);
  return vs.length ? vs.reduce((s, v) => s + v, 0) / vs.length : null;
}
function grade(avg) {
  if (avg == null) return { g: '—', cls: 'flat' };
  if (avg < 0.10) return { g: 'A — well diversified', cls: 'pos' };
  if (avg < 0.25) return { g: 'B — decent', cls: 'pos' };
  if (avg < 0.45) return { g: 'C — clustered', cls: 'neg' };
  return { g: 'D — moves as one', cls: 'neg' };
}
function corrColor(c) {
  if (c == null) return 'background:var(--surface-2)';
  if (c >= 0.999) return 'background:var(--gold);color:#1a1206';
  if (c >= 0.5) return 'background:#6e1010;color:#f7d7d5';
  if (c >= 0.3) return 'background:#b3403b;color:#fff';
  if (c >= 0.15) return 'background:#6a4d1c';
  if (c >= -0.1) return 'background:#2b261e';
  return 'background:#2a6a4a;color:#dff5e9';
}

// ---------- TAB: correlation ----------
function corrTab(body) {
  const algos = CORR.algos.slice();
  body.innerHTML = `
    <div class="grid grid-2" style="margin-bottom:22px;align-items:start">
      <div class="card"><div class="card-head"><h3>Diversifier finder</h3><span class="sub">least-correlated partners</span></div>
        <div class="card-pad">
          <select id="cf-sel" style="width:100%;margin-bottom:12px">${algos.map(a => `<option value="${a.id}" ${a.id === IV_IMBALANCE ? 'selected' : ''}>${escapeHtml(a.short)}</option>`).join('')}</select>
          <div id="cf-out"></div>
        </div>
      </div>
      <div class="card"><div class="card-head"><h3>How to read it</h3></div><div class="card-pad" style="font-size:.85rem;color:var(--ink-2)">
        <p>Correlation of <b>daily P&L</b> (−1 to +1). Two algos at <b>+1</b> win and lose together — stacking them doubles risk, not diversification. Near <b>0</b> or <b>negative</b> = they move independently → smoother combined equity.</p>
        <div style="margin-top:14px;display:flex;flex-direction:column;gap:6px;font-family:var(--mono);font-size:.72rem">
          <span><span class="swatch" style="background:#2a6a4a"></span> &lt; −0.1 &nbsp;diversifying</span>
          <span><span class="swatch" style="background:#2b261e;border:1px solid var(--border)"></span> −0.1 … 0.15 &nbsp;independent</span>
          <span><span class="swatch" style="background:#6a4d1c"></span> 0.15 … 0.3 &nbsp;mild overlap</span>
          <span><span class="swatch" style="background:#b3403b"></span> 0.3 … 0.5 &nbsp;correlated</span>
          <span><span class="swatch" style="background:#6e1010"></span> ≥ 0.5 &nbsp;moves as one</span>
        </div>
      </div>
    </div>
    <div class="card"><div class="card-head"><h3>Correlation matrix</h3>
      <span class="sub"><select id="cm-cat" style="font-size:.78rem">
        <option value="all">all ${algos.length}</option><option value="credit_spread">credit spreads</option><option value="option_buying">option buying</option></select></span></div>
      <div class="card-pad" style="overflow:auto" id="cm-wrap"></div>
    </div>`;

  const finder = () => {
    const id = body.querySelector('#cf-sel').value;
    const ranked = CORR.algos.filter(a => a.id !== id)
      .map(a => ({ a, c: pairCorr(id, a.id) })).filter(x => x.c != null)
      .sort((x, y) => x.c - y.c);
    const row = ({ a, c }) => `<tr><td>${escapeHtml(a.short)}</td><td>${bookTag(a.category)}</td>
      <td class="num"><span style="padding:1px 7px;border-radius:5px;${corrColor(c)}">${c.toFixed(2)}</span></td>
      <td class="num ${pnlClass(a.total_pts)}">${fmtPts(a.total_pts)}</td><td class="num muted">${a.sharpe ?? '—'}</td></tr>`;
    body.querySelector('#cf-out').innerHTML = `
      <div class="eyebrow" style="margin:4px 0 8px">Best diversifiers (lowest correlation)</div>
      <div class="hscroll"><table class="data" style="font-size:.78rem"><tbody>${ranked.slice(0, 6).map(row).join('')}</tbody></table></div>
      <div class="eyebrow" style="margin:16px 0 8px">Most redundant (highest correlation)</div>
      <div class="hscroll"><table class="data" style="font-size:.78rem"><tbody>${ranked.slice(-3).reverse().map(row).join('')}</tbody></table></div>`;
  };
  const heat = () => {
    const cat = body.querySelector('#cm-cat').value;
    const list = (cat === 'all' ? algos : algos.filter(a => a.category === cat));
    const cell = 17;
    const head = `<div style="display:flex"><div style="width:140px;flex-shrink:0;position:sticky;left:0;z-index:2;background:var(--surface-1)"></div>${list.map(a => `<div title="${escapeHtml(a.short)}" style="width:${cell}px;flex-shrink:0;writing-mode:vertical-rl;transform:rotate(180deg);font-size:8px;color:var(--ink-3);white-space:nowrap;overflow:hidden;height:90px">${escapeHtml(a.short)}</div>`).join('')}</div>`;
    const rows = list.map(r => `<div style="display:flex;align-items:center">
      <div style="width:140px;flex-shrink:0;position:sticky;left:0;z-index:1;background:var(--surface-1);font-size:.7rem;color:var(--ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:6px">${escapeHtml(r.short)}</div>
      ${list.map(c => { const v = pairCorr(r.id, c.id); return `<div title="${escapeHtml(r.short)} × ${escapeHtml(c.short)} = ${v == null ? 'n/a' : v.toFixed(2)}" style="width:${cell}px;height:${cell}px;flex-shrink:0;${corrColor(v)};border:1px solid var(--bg)"></div>`; }).join('')}
    </div>`).join('');
    body.querySelector('#cm-wrap').innerHTML = head + rows;
  };
  finder(); heat();
  const onCh = e => { if (e.target.id === 'cf-sel') finder(); else if (e.target.id === 'cm-cat') heat(); };
  body.addEventListener('change', onCh);
  cleanups.push(() => body.removeEventListener('change', onCh));
}

// ---------- TAB: builder ----------
function builderTab(body, preset) {
  const sel = new Set([...preset].filter(id => DAILY.has(id)));
  let ddMode = 'combined', stressOn = false;
  body.innerHTML = `
    <div class="split">
      <div class="card card-pad" style="max-height:680px;overflow:auto">
        <div class="eyebrow" style="margin-bottom:8px">Pick strategies</div>
        <input type="search" id="b-search" placeholder="Filter…" style="width:100%;margin-bottom:8px">
        <button class="btn primary" id="b-suggest" style="width:100%;margin-bottom:6px">✦ Suggest well-rounded 5</button>
        <button class="btn" id="b-complement" style="width:100%;margin-bottom:6px">✦ Diversify my picks</button>
        <button class="btn ghost" id="b-clear" style="width:100%;margin-bottom:10px">Clear</button>
        <div id="b-list"></div>
      </div>
      <div>
        <div id="b-complement-out" style="margin-bottom:14px"></div>
        <div id="b-gapfill-out" style="margin-bottom:14px"></div>
        <div id="b-score" style="margin-bottom:14px"></div>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
          <div class="seg" id="b-ddmode">
            <span class="seg-label">Drawdown</span>
            <button data-dd="combined" class="active">Combined band</button>
            <button data-dd="strategy">Per-strategy</button>
          </div>
          <button class="btn" id="b-gapfill" style="margin-left:auto">✦ Fill drawdown gaps</button>
        </div>
        <div class="chart-frame"><div class="chart-canvas-wrap" style="height:420px"><canvas id="b-canvas"></canvas></div></div>
        <div id="b-detail" style="margin-top:18px"></div>
      </div>
    </div>`;
  const search = { q: '' };
  const list = () => {
    const algos = CORR.algos.filter(a => (a.short || '').toLowerCase().includes(search.q.toLowerCase()))
      .sort((x, y) => y.total_pts - x.total_pts);
    body.querySelector('#b-list').innerHTML = algos.map(a => `
      <label style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:.8rem;cursor:pointer">
        <input type="checkbox" data-b="${a.id}" ${sel.has(a.id) ? 'checked' : ''}>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(a.short)}</span>
        <span class="mono muted" style="font-size:.68rem">${fmtPts(a.total_pts, false)}</span></label>`).join('');
  };
  const draw = () => {
    const ids = [...sel];
    const host = document.querySelector('#b-score');
    if (!ids.length) { host.innerHTML = `<div class="note">Pick at least one strategy.</div>`; if (chart) { chart.destroy(); chart = null; } document.querySelector('#b-detail').innerHTML = ''; return; }
    const c = combined(ids);
    const avg = avgPairCorr(ids); const gr = grade(avg);
    const naiveDD = ids.reduce((s, id) => s + soloMaxDD(id), 0);
    host.innerHTML = scorecard([
      { label: 'Total pts (1 lot ea)', value: fmtPts(c.total), sm: true, cls: pnlClass(c.total) },
      { label: 'Blended Sharpe', value: c.sharpe != null ? c.sharpe.toFixed(2) : '—', sm: true },
      { label: 'Blended max DD', value: fmtPts(c.maxDD, false), sm: true, cls: 'neg', delta: `vs ${fmtPts(naiveDD, false)} un-diversified` },
      { label: 'Avg correlation', value: avg != null ? avg.toFixed(2) : '—', sm: true, cls: gr.cls },
      { label: 'Diversification', value: gr.g.split(' — ')[0], sm: true, cls: gr.cls, delta: gr.g.split(' — ')[1] || '' },
    ]);
    if (chart) chart.destroy();
    // overlays (thin, faint, distinct colour) — drawn first so they sit under the combined line
    const overlays = ids.map((id, i) => {
      const s = soloSeries(id); const col = OVERLAY[i % OVERLAY.length];
      return {
        label: BYID.get(id) ? BYID.get(id).short : id,
        data: s.series.map(p => ({ x: p.x, y: p.y })),
        _under: s.under,
        borderColor: col + '80', borderWidth: 1, fill: false, pointRadius: 0, tension: 0.06, order: 2,
        segment: { borderColor: ddSegment(col + '80', () => ddMode === 'strategy') },
      };
    });
    // averaged combined line (sum ÷ N) so it shares scale with the overlays
    const n = ids.length;
    const combinedDs = {
      label: 'Combined equity (avg)', data: c.series.map(p => ({ x: p.x, y: p.y / n })),
      borderColor: '#B79CF0', backgroundColor: 'rgba(183,156,240,0.10)', borderWidth: 2.6, fill: true, pointRadius: 0, tension: 0.06, order: 1,
    };
    const ddRanges = underwaterRanges(c.series);
    const stressRanges = stressWindows(ids).ranges;
    chart = new Chart(document.querySelector('#b-canvas'), {
      type: 'line', data: { datasets: [...overlays, combinedDs] },
      plugins: [
        ddBandPlugin(() => stressRanges, () => stressOn, 'rgba(232,163,61,0.22)'),
        ddBandPlugin(() => ddRanges, () => ddMode === 'combined'),
      ],
      options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        scales: { x: { type: 'time', time: { tooltipFormat: 'dd MMM yyyy' }, ticks: { color: TICK, maxTicksLimit: 10 }, grid: { color: GRID } },
          y: { ticks: { color: TICK }, grid: { color: GRID } } }, plugins: { legend: { display: false } } },
    });
    document.querySelector('#b-detail').innerHTML = `
      <div class="eyebrow" style="margin-bottom:10px">Members · avg correlation to the rest <span class="muted" style="text-transform:none;letter-spacing:0">· 2026 pts, win rate &amp; avg win/loss are YTD · click a row for the deep dive</span></div>
      <div class="table-wrap"><table class="data" style="font-size:.8rem"><thead><tr><th>Algo</th><th>Book</th><th class="num">2026 pts</th><th class="num">Win rate</th><th class="num">Avg win</th><th class="num">Avg loss</th><th class="num">Sharpe</th><th class="num">Solo max DD</th><th class="num">Avg corr</th><th></th></tr></thead><tbody>
      ${ids.map((id, i) => { const a = BYID.get(id); const ac = avgCorrTo(id, ids); const wr = WR.get(id);
        const ts = tradeStats((EQBYID.get(id)?.curves_2026 || {}).trade_pts); return `<tr class="b-row-link" data-open="${id}"><td><span class="swatch" style="background:${OVERLAY[i % OVERLAY.length]}"></span> ${escapeHtml(a.short)}</td><td>${bookTag(a.category)}</td>
        <td class="num ${pnlClass(ts.totalPts)}">${ts.trades ? fmtPts(ts.totalPts) : '—'}</td><td class="num">${wr != null ? wr.toFixed(1) + '%' : '—'}</td>
        <td class="num pos">${ts.trades ? fmtPts(ts.avgWin, false) : '—'}</td><td class="num neg">${ts.trades ? fmtPts(ts.avgLoss, false) : '—'}</td>
        <td class="num muted">${a.sharpe ?? '—'}</td>
        <td class="num neg">${fmtPts(soloMaxDD(id), false)}</td>
        <td class="num"><span style="padding:1px 6px;border-radius:5px;${corrColor(ac)}">${ac != null ? ac.toFixed(2) : '—'}</span></td>
        <td><button class="btn ghost" data-bdel="${id}" title="Remove from portfolio" style="padding:2px 9px">✕</button></td></tr>`; }).join('')}
      </tbody></table></div>`;
  };
  const complement = () => {
    const host = document.querySelector('#b-complement-out');
    if (!sel.size) { host.innerHTML = `<div class="note">Pick at least one strategy, then I'll suggest 5 complements that lower correlation &amp; drawdown.</div>`; return; }
    const picks = suggestComplement([...sel], 5);
    if (!picks.length) { host.innerHTML = `<div class="note">No further diversifiers found.</div>`; return; }
    host.innerHTML = `<div class="card"><div class="card-head"><h3>Best 5 complements to your book</h3>
        <span class="sub" style="display:flex;align-items:center;gap:10px">lowest correlation, lowest blended DD <button class="btn ghost" id="b-comp-x" style="padding:2px 9px">✕</button></span></div>
      <div class="card-pad"><table class="data" style="font-size:.8rem"><thead><tr><th>Strategy</th><th>Book</th><th class="num">Corr to book</th><th class="num">Blended DD if added</th><th class="num">Total pts</th><th></th></tr></thead><tbody>
      ${picks.map(p => { const a = BYID.get(p.id); return `<tr><td>${escapeHtml(a.short)}</td><td>${bookTag(a.category)}</td>
        <td class="num"><span style="padding:1px 6px;border-radius:5px;${corrColor(p.corr)}">${p.corr.toFixed(2)}</span></td>
        <td class="num neg">${fmtPts(p.ddAfter, false)}</td>
        <td class="num ${pnlClass(a.total_pts)}">${fmtPts(a.total_pts)}</td>
        <td><button class="btn" data-cadd="${p.id}" style="padding:3px 10px">+ add</button></td></tr>`; }).join('')}
      </tbody></table></div></div>`;
  };
  const gapfill = () => {
    const host = document.querySelector('#b-gapfill-out');
    const close = `<button class="btn ghost" id="b-gap-x" style="padding:2px 9px">✕</button>`;
    if (sel.size < 2) { host.innerHTML = `<div class="card"><div class="card-head"><h3>Fill drawdown gaps</h3><span class="sub">${close}</span></div><div class="card-pad note">Pick at least two strategies, then I'll find ones that print while your book bleeds.</div></div>`; return; }
    const sw = stressWindows([...sel]);
    if (!sw.count) { host.innerHTML = `<div class="card"><div class="card-head"><h3>Fill drawdown gaps</h3><span class="sub">${close}</span></div><div class="card-pad note">No common drawdown windows — &gt;50% of your book is rarely underwater together. 🎉</div></div>`; return; }
    const picks = suggestGapFillers([...sel], 5);
    const rows = picks.length ? picks.map(p => { const a = BYID.get(p.id); return `<tr><td>${escapeHtml(a.short)}</td><td>${bookTag(a.category)}</td>
        <td class="num pos">${fmtPts(p.avg, false)}</td>
        <td class="num muted">${p.coverage}/${sw.count} days</td>
        <td class="num neg">${fmtPts(soloMaxDD(p.id), false)}</td>
        <td><button class="btn" data-gadd="${p.id}" style="padding:3px 10px">+ add</button></td></tr>`; }).join('')
      : `<tr><td colspan="6" class="muted" style="padding:10px">No candidate stays profitable across enough of your stress days.</td></tr>`;
    host.innerHTML = `<div class="card"><div class="card-head"><h3>Holds up when your book bleeds</h3>
        <span class="sub" style="display:flex;align-items:center;gap:10px">avg pts on your ${sw.count} stress days · ${sw.ranges.length} windows ${close}</span></div>
      <div class="card-pad"><table class="data" style="font-size:.8rem"><thead><tr><th>Strategy</th><th>Book</th><th class="num">Avg pts in stress</th><th class="num">Coverage</th><th class="num">Solo max DD</th><th></th></tr></thead><tbody>
      ${rows}</tbody></table>
      <p class="muted" style="font-size:.72rem;margin-top:8px">Stress = days &gt;50% of your picks are in a sustained (3+ day) drawdown, shaded amber on the chart. Ranked by avg P&amp;L on exactly those days.</p></div></div>`;
  };
  list(); draw();
  const onCh = e => { const b = e.target.closest('input[data-b]'); if (b) { b.checked ? sel.add(b.dataset.b) : sel.delete(b.dataset.b); draw(); } };
  const clearOut = () => { document.querySelector('#b-complement-out').innerHTML = ''; document.querySelector('#b-gapfill-out').innerHTML = ''; };
  const onClick = e => {
    if (e.target.id === 'b-clear') { sel.clear(); stressOn = false; list(); draw(); clearOut(); return; }
    if (e.target.id === 'b-suggest') { sel.clear(); stressOn = false; suggest(5).forEach(id => sel.add(id)); list(); draw(); clearOut(); return; }
    if (e.target.id === 'b-complement') { complement(); return; }
    if (e.target.id === 'b-comp-x') { document.querySelector('#b-complement-out').innerHTML = ''; return; }
    if (e.target.id === 'b-gapfill') { stressOn = true; gapfill(); draw(); return; }
    if (e.target.id === 'b-gap-x') { stressOn = false; document.querySelector('#b-gapfill-out').innerHTML = ''; draw(); return; }
    const add = e.target.closest('button[data-cadd]'); if (add) { sel.add(add.dataset.cadd); list(); draw(); complement(); return; }
    const gadd = e.target.closest('button[data-gadd]'); if (gadd) { sel.add(gadd.dataset.gadd); list(); draw(); gapfill(); return; }
    const del = e.target.closest('button[data-bdel]'); if (del) { sel.delete(del.dataset.bdel); list(); draw(); return; }
    const openRow = e.target.closest('tr[data-open]'); if (openRow) { router.go('#/algo/' + openRow.dataset.open); }
  };
  const onIn = e => { if (e.target.id === 'b-search') { search.q = e.target.value; list(); } };
  const onDd = e => {
    const b = e.target.closest('#b-ddmode button[data-dd]'); if (!b) return;
    ddMode = b.dataset.dd;
    [...body.querySelectorAll('#b-ddmode button')].forEach(x => x.classList.toggle('active', x.dataset.dd === ddMode));
    draw();
  };
  body.addEventListener('change', onCh); body.addEventListener('click', onClick); body.addEventListener('click', onDd); body.addEventListener('input', onIn);
  cleanups.push(() => { body.removeEventListener('change', onCh); body.removeEventListener('click', onClick); body.removeEventListener('click', onDd); body.removeEventListener('input', onIn); });
}

// greedy: maximise diversification while keeping positive expectancy
function suggest(n) {
  const pos = CORR.algos.filter(a => a.total_pts > 0).slice();
  if (!pos.length) return [];
  pos.sort((a, b) => b.total_pts - a.total_pts);
  const picked = [pos[0].id];
  while (picked.length < n) {
    let best = null, bestScore = Infinity;
    for (const a of pos) {
      if (picked.includes(a.id)) continue;
      const ac = avgCorrTo(a.id, picked); if (ac == null) continue;
      // prefer low correlation, tie-break high pts
      const score = ac - (a.total_pts / 50000);
      if (score < bestScore) { bestScore = score; best = a.id; }
    }
    if (!best) break; picked.push(best);
  }
  return picked;
}

// greedy: given the current book, pick n complements that best balance lower blended DD + low correlation
// (positive expectancy required). Returns [{ id, corr, ddAfter }] in pick order.
function suggestComplement(currentIds, n = 5) {
  const have = currentIds.filter(id => DAILY.has(id));
  if (!have.length) return [];
  const S = have.slice();
  const out = [];
  while (out.length < n) {
    const cand = CORR.algos.filter(a => a.total_pts > 0 && DAILY.has(a.id) && !S.includes(a.id));
    if (!cand.length) break;
    const scored = cand.map(a => ({
      id: a.id,
      dd: combined([...S, a.id]).maxDD,       // negative; less negative = better
      corr: avgCorrTo(a.id, S) ?? 0,          // lower = better
    }));
    const dds = scored.map(s => s.dd), cs = scored.map(s => s.corr);
    const minDd = Math.min(...dds), maxDd = Math.max(...dds);
    const minC = Math.min(...cs), maxC = Math.max(...cs);
    const norm = (v, lo, hi) => hi > lo ? (v - lo) / (hi - lo) : 1;
    let best = null, bestScore = -Infinity;
    for (const s of scored) {
      const ddNorm = norm(s.dd, minDd, maxDd);          // 1 = least DD
      const corrNorm = 1 - norm(s.corr, minC, maxC);    // 1 = lowest corr
      const score = 0.5 * ddNorm + 0.5 * corrNorm;
      if (score > bestScore) { bestScore = score; best = s; }
    }
    if (!best) break;
    S.push(best.id); out.push({ id: best.id, corr: best.corr, ddAfter: best.dd });
  }
  return out;
}

// ---------- TAB: doctor ----------
function doctorTab(body) {
  const held = new Set([IV_IMBALANCE].filter(id => DAILY.has(id)));
  body.innerHTML = `
    <div class="note" style="margin-bottom:18px">Tell the desk what you actually hold — it grades how diversified your book is and names the strategies that would smooth it most. Defaulted to your <b>IV-Imbalance</b> position.</div>
    <div class="split">
      <div class="card card-pad" style="max-height:560px;overflow:auto">
        <div class="eyebrow" style="margin-bottom:8px">Your holdings</div>
        <input type="search" id="d-search" placeholder="Add a holding…" style="width:100%;margin-bottom:10px">
        <div id="d-list"></div>
      </div>
      <div>
        <div id="d-grade" style="margin-bottom:16px"></div>
        <div class="card"><div class="card-head"><h3>Add these to diversify</h3><span class="sub">lowest correlation to your book, still profitable</span></div>
          <div class="card-pad" id="d-suggest"></div></div>
      </div>
    </div>`;
  const search = { q: '' };
  const list = () => {
    const algos = CORR.algos.filter(a => (a.short || '').toLowerCase().includes(search.q.toLowerCase())).sort((x, y) => y.total_pts - x.total_pts);
    body.querySelector('#d-list').innerHTML = algos.map(a => `
      <label style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:.8rem;cursor:pointer">
        <input type="checkbox" data-d="${a.id}" ${held.has(a.id) ? 'checked' : ''}>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(a.short)}</span>
        <span class="mono muted" style="font-size:.68rem">${fmtPts(a.total_pts, false)}</span></label>`).join('');
  };
  const draw = () => {
    const ids = [...held];
    const gradeHost = document.querySelector('#d-grade'), sugHost = document.querySelector('#d-suggest');
    if (!ids.length) { gradeHost.innerHTML = `<div class="note">Select what you hold.</div>`; sugHost.innerHTML = ''; return; }
    const avg = avgPairCorr(ids); const gr = grade(avg); const c = combined(ids);
    gradeHost.innerHTML = scorecard([
      { label: 'Diversification grade', value: gr.g.split(' — ')[0], sm: true, cls: gr.cls, delta: gr.g.split(' — ')[1] || (ids.length === 1 ? 'single holding' : '') },
      { label: 'Avg correlation', value: avg != null ? avg.toFixed(2) : '—', sm: true, cls: gr.cls },
      { label: 'Book total pts', value: fmtPts(c.total), sm: true, cls: pnlClass(c.total) },
      { label: 'Book max DD', value: fmtPts(c.maxDD, false), sm: true, cls: 'neg' },
    ]);
    const cand = CORR.algos.filter(a => !held.has(a.id) && a.total_pts > 0)
      .map(a => ({ a, c: avgCorrTo(a.id, ids) })).filter(x => x.c != null)
      .sort((x, y) => x.c - y.c).slice(0, 6);
    sugHost.innerHTML = `<table class="data" style="font-size:.8rem"><thead><tr><th>Strategy</th><th>Book</th><th class="num">Corr to yours</th><th class="num">Total pts</th><th class="num">Sharpe</th><th></th></tr></thead><tbody>
      ${cand.map(({ a, c }) => `<tr><td>${escapeHtml(a.short)}</td><td>${bookTag(a.category)}</td>
        <td class="num"><span style="padding:1px 6px;border-radius:5px;${corrColor(c)}">${c.toFixed(2)}</span></td>
        <td class="num ${pnlClass(a.total_pts)}">${fmtPts(a.total_pts)}</td><td class="num muted">${a.sharpe ?? '—'}</td>
        <td><button class="btn" data-add="${a.id}" style="padding:3px 10px">+ add</button></td></tr>`).join('')}
    </tbody></table>`;
  };
  list(); draw();
  const onCh = e => { const b = e.target.closest('input[data-d]'); if (b) { b.checked ? held.add(b.dataset.d) : held.delete(b.dataset.d); list(); draw(); } };
  const onClick = e => { const add = e.target.closest('button[data-add]'); if (add) { held.add(add.dataset.add); list(); draw(); } };
  const onIn = e => { if (e.target.id === 'd-search') { search.q = e.target.value; list(); } };
  body.addEventListener('change', onCh); body.addEventListener('click', onClick); body.addEventListener('input', onIn);
  cleanups.push(() => { body.removeEventListener('change', onCh); body.removeEventListener('click', onClick); body.removeEventListener('input', onIn); });
}
