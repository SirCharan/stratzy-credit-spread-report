// charts.js — Charts: equity overlay (zoom/pan/select-range) + what-if + portfolio.
// Folds equity.html + what-if.html + option-buying-portfolio.html.

import { load } from '../data.js';
import * as router from '../router.js';
import { sectionHead, scorecard } from '../components.js';
import { fmtPts, fmtLakh, fmtInr, fmtPct, fmtNum, escapeHtml, pnlClass, maxDrawdown } from '../util.js';
import { ddBandPlugin, ddSegment, underwaterRanges, underwaterFlags } from '../chartdd.js';

const OB_OVERLAYS = {
  '68583ce39edddcb829103b96': { short: 'Burst GRID', color: '#E8A33D' },
  '685855ef9edddcb829103b9c': { short: 'Vacuum GRID', color: '#FB923C' },
};
const colorMap = new Map();
let chart = null;            // active Chart.js instance
let cleanupFns = [];

const GRID = '#2b261e';
const TICK = '#8A8070';

export async function render(root, params, query) {
  const [equity, st] = await Promise.all([load('equity_curves'), load('option_buying_stratzy').catch(() => null)]);

  let tab = (query && query.tab) || 'overlay';
  root.innerHTML = `<div class="fade-in">
    ${sectionHead('The chart room', 'Equity, overlaid',
      `Stack equity curves to see who actually compounds, combine two strategies into one book, or build an equal-weight portfolio. Scroll to zoom, Shift-drag to pan, or switch to <b>Select range</b> to measure any stretch.`)}
    <div class="seg" id="chart-tabs" style="margin-bottom:20px">
      <span class="seg-label">View</span>
      <button data-tab="overlay">Overlay</button>
      <button data-tab="whatif">What-if combiner</button>
      <button data-tab="portfolio">Portfolio builder</button>
    </div>
    <div id="chart-body"></div>
  </div>`;

  const tabsEl = root.querySelector('#chart-tabs');
  const body = root.querySelector('#chart-body');
  const setTab = (t) => {
    tab = t;
    [...tabsEl.querySelectorAll('button')].forEach(b => b.classList.toggle('active', b.dataset.tab === t));
    teardown();
    if (t === 'overlay') overlayTab(body, equity, query);
    else if (t === 'whatif') whatifTab(body, equity);
    else portfolioTab(body, st, query);
  };
  tabsEl.addEventListener('click', e => { const b = e.target.closest('button[data-tab]'); if (b) setTab(b.dataset.tab); });
  setTab(tab);

  return () => teardown();
}

function teardown() {
  if (chart) { chart.destroy(); chart = null; }
  cleanupFns.forEach(fn => { try { fn(); } catch {} });
  cleanupFns = [];
}

function colorFor(id, fallbackIdx, palette) {
  if (OB_OVERLAYS[id]) return OB_OVERLAYS[id].color;
  if (!colorMap.has(id)) colorMap.set(id, palette[colorMap.size % palette.length]);
  return colorMap.get(id);
}

// enrich a curve into {x, y, step, t} where step = per-point change
function enrich(points, xmode) {
  let prev = null;
  return points.map((p, i) => {
    const t = xmode === 'trade' ? (p.trade ?? i + 1) : new Date(p.x).getTime();
    const step = p.day_pnl != null ? p.day_pnl : (prev == null ? p.y : p.y - prev);
    prev = p.y;
    return { x: p.x, t, y: p.y, step };
  });
}

/* ======================================================================
   TAB 1 — OVERLAY
   ====================================================================== */
function overlayTab(body, equity, query) {
  const palette = equity.palette;
  const st = {
    cat: (query && query.cat) || 'all',
    period: 'all', xmode: 'daily', ymode: 'pts',
    selected: new Set(), overlays: new Set(), selectMode: false, combined: false,
    dd: (query && query.dd) || 'off',
  };
  if (query && query.ob_burst) st.overlays.add('68583ce39edddcb829103b96');
  if (query && query.ob_vacuum) st.overlays.add('685855ef9edddcb829103b9c');
  if (query && query.combined) st.combined = true;

  const presets = equity.presets;
  const applyPreset = (pid) => {
    const p = presets.find(z => z.id === pid); if (!p) return;
    st.selected = new Set(p.ids);
    if (p.use_2026) st.period = '2026';
    if (p.category && p.category !== 'mixed') st.cat = p.category;
  };
  if (query && query.preset) applyPreset(query.preset);
  else applyPreset(st.cat === 'credit_spread' ? 'cs_top5' : st.cat === 'option_buying' ? 'ob_top5' : 'overnight_trio');

  body.innerHTML = `
    <div class="seg" id="ov-cat" style="margin-bottom:14px">
      <span class="seg-label">Book</span>
      <button data-cat="all">All</button><button data-cat="credit_spread">Credit spreads</button><button data-cat="option_buying">Option buying</button>
    </div>
    <div id="ov-presets" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px"></div>
    <div style="display:grid;grid-template-columns:260px 1fr;gap:18px;align-items:start">
      <div class="card card-pad" style="max-height:640px;overflow:auto">
        <div class="eyebrow" style="margin-bottom:10px">Pick algos</div>
        <div id="ov-picker"></div>
        <div class="divider"></div>
        <div class="eyebrow" style="margin-bottom:10px">OB overlays</div>
        <div id="ov-overlays"></div>
      </div>
      <div>
        <div class="controls" style="margin-bottom:12px">
          <div class="seg" id="ov-x"><span class="seg-label">X</span><button data-x="daily">By day</button><button data-x="trade">By trade</button></div>
          <div class="seg" id="ov-y"><span class="seg-label">Y</span><button data-y="pts">Points</button><button data-y="inr">₹ / lot</button></div>
          <div class="seg" id="ov-p"><span class="seg-label">Period</span><button data-p="all">All-time</button><button data-p="2026">2026</button></div>
          <div class="seg" id="ov-dd"><span class="seg-label">Drawdown</span><button data-dd="off">Off</button><button data-dd="combined">Combined band</button><button data-dd="strategy">Per-strategy</button></div>
          <button class="btn" id="ov-combined">✦ Combined</button>
          <button class="btn" id="ov-select">⌖ Select range</button>
          <button class="btn" id="ov-reset">Reset zoom</button>
          <button class="btn ghost" id="ov-clear">Clear</button>
        </div>
        <div class="chart-frame">
          <div class="chart-canvas-wrap" id="ov-wrap"><canvas id="ov-canvas"></canvas></div>
        </div>
        <p class="muted" style="font-size:.74rem;margin-top:8px">Scroll = zoom · Shift-drag = pan · drag = box-zoom (or measure, in Select-range mode)</p>
        <div id="ov-range" style="margin-top:14px"></div>
      </div>
    </div>`;

  const seg = (id, key, val) => [...body.querySelectorAll(`#${id} button`)].forEach(b => b.classList.toggle('active', b.dataset[key] === st[val]));
  const renderPresets = () => {
    body.querySelector('#ov-presets').innerHTML = presets
      .filter(p => st.cat === 'all' ? true : (p.category === st.cat))
      .map(p => `<button class="btn" data-preset="${p.id}">${escapeHtml(p.label)}</button>`).join('');
  };
  const renderPicker = () => {
    const list = equity.algos.filter(a => st.cat === 'all' ? true : a.category === st.cat);
    body.querySelector('#ov-picker').innerHTML = list.map(a => `
      <label style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:.8rem;cursor:pointer">
        <input type="checkbox" data-pick="${a.id}" ${st.selected.has(a.id) ? 'checked' : ''}>
        <span class="swatch" style="background:${colorFor(a.id, 0, palette)}"></span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(a.short || a.name)}</span>
        <span class="mono muted" style="font-size:.7rem">${fmtPts(a.total_pts, false)}</span>
      </label>`).join('');
    body.querySelector('#ov-overlays').innerHTML = Object.entries(OB_OVERLAYS).map(([id, o]) => `
      <label style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:.8rem;cursor:pointer">
        <input type="checkbox" data-ov="${id}" ${st.overlays.has(id) ? 'checked' : ''}>
        <span class="swatch" style="background:${o.color}"></span> ${o.short} <span class="muted">(dashed)</span>
      </label>`).join('');
  };
  const syncSegs = () => { seg('ov-cat', 'cat', 'cat'); seg('ov-x', 'x', 'xmode'); seg('ov-y', 'y', 'ymode'); seg('ov-p', 'p', 'period'); seg('ov-dd', 'dd', 'dd'); };

  const rebuild = () => {
    renderPresets(); renderPicker(); syncSegs();
    body.querySelector('#ov-combined')?.classList.toggle('primary', st.combined);
    drawOverlay(equity, st);
  };

  // events
  const onClick = (e) => {
    const c = e.target.closest('#ov-cat button'); if (c) { st.cat = c.dataset.cat; if (![...st.selected].some(id => (equity.algos.find(a=>a.id===id)||{}).category === st.cat) && st.cat!=='all') { applyPreset(st.cat==='credit_spread'?'cs_top5':'ob_top5'); } rebuild(); return; }
    const x = e.target.closest('#ov-x button'); if (x) { st.xmode = x.dataset.x; rebuild(); return; }
    const y = e.target.closest('#ov-y button'); if (y) { st.ymode = y.dataset.y; rebuild(); return; }
    const p = e.target.closest('#ov-p button'); if (p) { st.period = p.dataset.p; rebuild(); return; }
    const dd = e.target.closest('#ov-dd button'); if (dd) { st.dd = dd.dataset.dd; rebuild(); return; }
    const pr = e.target.closest('#ov-presets button'); if (pr) { applyPreset(pr.dataset.preset); rebuild(); return; }
    if (e.target.closest('#ov-reset')) { chart?.resetZoom(); updateRange(st); return; }
    if (e.target.closest('#ov-clear')) { st.selected.clear(); st.overlays.clear(); rebuild(); return; }
    if (e.target.closest('#ov-select')) { st.selectMode = !st.selectMode; body.querySelector('#ov-select').classList.toggle('primary', st.selectMode); body.querySelector('#ov-wrap').style.cursor = st.selectMode ? 'col-resize' : ''; return; }
    if (e.target.closest('#ov-combined')) { st.combined = !st.combined; body.querySelector('#ov-combined').classList.toggle('primary', st.combined); drawOverlay(equity, st); return; }
  };
  const onChange = (e) => {
    const pk = e.target.closest('input[data-pick]'); if (pk) { pk.checked ? st.selected.add(pk.dataset.pick) : st.selected.delete(pk.dataset.pick); drawOverlay(equity, st); return; }
    const ov = e.target.closest('input[data-ov]'); if (ov) { ov.checked ? st.overlays.add(ov.dataset.ov) : st.overlays.delete(ov.dataset.ov); drawOverlay(equity, st); return; }
  };
  body.addEventListener('click', onClick);
  body.addEventListener('change', onChange);
  cleanupFns.push(() => { body.removeEventListener('click', onClick); body.removeEventListener('change', onChange); });

  rebuild();
}

function drawOverlay(equity, st) {
  if (chart) { chart.destroy(); chart = null; }
  const ctx = document.getElementById('ov-canvas'); if (!ctx) return;
  const ids = [...st.selected, ...st.overlays];
  const datasets = ids.map(id => {
    const a = equity.algos.find(z => z.id === id); if (!a) return null;
    const root = st.period === '2026' ? a.curves_2026 : a.curves;
    const pts = root && root[`${st.xmode}_${st.ymode}`];
    if (!pts || !pts.length) return null;
    const en = enrich(pts, st.xmode);
    const isOv = st.overlays.has(id);
    const color = colorFor(id, 0, equity.palette);
    return {
      label: (a.short || a.name) + (isOv ? ' (OB overlay)' : ''),
      data: en.map(p => ({ x: st.xmode === 'trade' ? p.t : p.x, y: p.y })),
      almanac: en,
      _under: st.dd === 'strategy' ? underwaterFlags(en.map(p => ({ y: p.y }))) : undefined,
      borderColor: color, backgroundColor: color,
      borderWidth: isOv ? 2.4 : 2, borderDash: isOv ? [7, 4] : [],
      segment: { borderColor: ddSegment(color, () => st.dd === 'strategy') },
      pointRadius: en.length > 100 ? 0 : 2, pointHoverRadius: 4, tension: 0.05,
    };
  }).filter(Boolean);

  // combined-book underwater ranges (daily mode only — date-axis band)
  let ddRanges = [];
  if (st.dd === 'combined' && st.xmode === 'daily' && st.selected.size >= 1) {
    const sel = [...st.selected].map(id => equity.algos.find(z => z.id === id)).filter(Boolean);
    const map = new Map();
    sel.forEach(a => {
      const root = st.period === '2026' ? a.curves_2026 : a.curves;
      (root && root[`daily_${st.ymode}`] || []).forEach(p => map.set(p.x, (map.get(p.x) || 0) + (p.day_pnl ?? 0)));
    });
    let cum = 0;
    ddRanges = underwaterRanges([...map.keys()].sort().map(d => ({ x: d, y: (cum += map.get(d)) })));
  }

  // optional equal-weight average (÷N) combined line over the SELECTED algos (daily mode only)
  if (st.combined && st.xmode === 'daily' && st.selected.size >= 2) {
    const sel = [...st.selected].map(id => equity.algos.find(z => z.id === id)).filter(Boolean);
    const map = new Map();
    sel.forEach(a => {
      const root = st.period === '2026' ? a.curves_2026 : a.curves;
      (root && root[`daily_${st.ymode}`] || []).forEach(p => map.set(p.x, (map.get(p.x) || 0) + (p.day_pnl ?? 0)));
    });
    const days = [...map.keys()].sort();
    let cum = 0;
    const en = days.map(d => { const step = map.get(d) / sel.length; cum += step; return { x: d, t: new Date(d).getTime(), y: cum, step }; });
    if (en.length) datasets.push({
      label: `Combined avg (${sel.length})`,
      data: en.map(p => ({ x: p.x, y: p.y })), almanac: en,
      borderColor: '#B79CF0', backgroundColor: 'rgba(183,156,240,0.10)',
      borderWidth: 3, borderDash: [], pointRadius: 0, pointHoverRadius: 4, tension: 0.05, fill: false,
    });
  }

  const isInr = st.ymode === 'inr';
  chart = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    plugins: [ddBandPlugin(() => ddRanges, () => st.dd === 'combined')],
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false, axis: 'x' },
      scales: {
        x: st.xmode === 'trade'
          ? { type: 'linear', ticks: { color: TICK, maxTicksLimit: 14 }, grid: { color: GRID } }
          : { type: 'time', time: { tooltipFormat: 'dd MMM yyyy' }, ticks: { color: TICK, maxTicksLimit: 14 }, grid: { color: GRID } },
        y: { ticks: { color: TICK, callback: v => isInr ? '₹' + (v / 1000).toFixed(0) + 'k' : v }, grid: { color: GRID } },
      },
      plugins: {
        legend: { position: 'bottom', labels: { color: '#C4BAA8', boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: items => st.xmode === 'trade' ? 'Trade #' + items[0].parsed.x : new Date(items[0].parsed.x).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }),
            label: item => {
              const en = item.dataset.almanac[item.dataIndex];
              const u = isInr ? '₹' : '';
              return `${item.dataset.label}: ${u}${Math.round(item.parsed.y).toLocaleString('en-IN')}  (Δ ${en ? (en.step >= 0 ? '+' : '') + Math.round(en.step) : '—'})`;
            },
          },
        },
        zoom: {
          pan: { enabled: true, mode: 'xy', modifierKey: 'shift', onPanComplete: () => updateRange(st) },
          zoom: { wheel: { enabled: true, speed: 0.08 }, pinch: { enabled: true }, drag: { enabled: () => !st.selectMode, backgroundColor: 'rgba(232,163,61,0.12)', borderColor: 'rgba(232,163,61,0.6)', borderWidth: 1 }, mode: 'xy', onZoomComplete: () => updateRange(st) },
          limits: { y: { min: 'original', max: 'original' } },
        },
      },
    },
  });
  attachSelect(st);
  drawFinalChips(st, datasets);
  setTimeout(() => updateRange(st), 60);
}

function drawFinalChips(st, datasets) {
  const host = document.getElementById('ov-range'); if (!host) return;
  // (range panel rendered by updateRange; final chips appended above it on first draw)
}

// ---- select-range + visible-range analysis ----
let selState = null;
function attachSelect(st) {
  const wrap = document.getElementById('ov-wrap'); if (!wrap || !chart) return;
  const canvas = chart.canvas;
  let rect = null, startX = null, startVal = null;
  const down = (e) => {
    if (!st.selectMode) return;
    const r = canvas.getBoundingClientRect();
    startX = e.clientX - r.left;
    startVal = chart.scales.x.getValueForPixel(startX);
    rect = document.createElement('div');
    Object.assign(rect.style, { position: 'absolute', top: '0', bottom: '0', background: 'rgba(183,156,240,0.16)', borderLeft: '1px solid #B79CF0', borderRight: '1px solid #B79CF0', left: startX + 'px', width: '0', pointerEvents: 'none', zIndex: 5 });
    wrap.appendChild(rect);
  };
  const move = (e) => {
    if (!rect) return;
    const r = canvas.getBoundingClientRect();
    const x = e.clientX - r.left;
    rect.style.left = Math.min(x, startX) + 'px';
    rect.style.width = Math.abs(x - startX) + 'px';
  };
  const up = (e) => {
    if (!rect) return;
    const r = canvas.getBoundingClientRect();
    const endVal = chart.scales.x.getValueForPixel(e.clientX - r.left);
    rect.remove(); rect = null;
    const lo = Math.min(startVal, endVal), hi = Math.max(startVal, endVal);
    renderRange(st, lo, hi, 'Selected range');
  };
  canvas.addEventListener('mousedown', down);
  window.addEventListener('mousemove', move);
  window.addEventListener('mouseup', up);
  cleanupFns.push(() => { canvas.removeEventListener('mousedown', down); window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); });
}
function updateRange(st) {
  if (!chart) return;
  renderRange(st, chart.scales.x.min, chart.scales.x.max, 'Visible range');
}
function renderRange(st, lo, hi, label) {
  const host = document.getElementById('ov-range'); if (!host || !chart) return;
  const isInr = st.ymode === 'inr';
  const num = (v) => st.xmode === 'trade' ? v : v;
  const cards = chart.data.datasets.map(ds => {
    const pts = ds.almanac.filter(p => p.t >= lo && p.t <= hi);
    if (pts.length < 2) return null;
    const ys = pts.map(p => p.y);
    const change = ys[ys.length - 1] - ys[0];
    let peak = ys[0], dd = 0, trough = ys[0], rise = 0;
    for (const v of ys) { peak = Math.max(peak, v); dd = Math.min(dd, v - peak); trough = Math.min(trough, v); rise = Math.max(rise, v - trough); }
    const u = isInr ? v => fmtLakh(v) : v => fmtPts(v);
    return `<div class="card card-pad" style="border-left:3px solid ${ds.borderColor}">
      <div style="font-weight:600;font-size:.85rem;margin-bottom:6px">${escapeHtml(ds.label)}</div>
      <div style="display:flex;gap:18px;flex-wrap:wrap;font-family:var(--mono);font-size:.76rem">
        <span>Δ <b class="${pnlClass(change)}">${isInr ? fmtLakh(change) : fmtPts(change)}</b></span>
        <span class="muted">max DD <span class="neg">${isInr ? fmtLakh(dd) : fmtPts(dd, false)}</span></span>
        <span class="muted">best rise <span class="pos">${isInr ? fmtLakh(rise) : fmtPts(rise, false)}</span></span>
        <span class="muted">pts ${pts.length}</span>
      </div></div>`;
  }).filter(Boolean);
  host.innerHTML = cards.length ? `<div class="eyebrow" style="margin-bottom:10px">${label}</div><div class="grid grid-3">${cards.join('')}</div>` : '';
}

/* ======================================================================
   TAB 2 — WHAT-IF
   ====================================================================== */
function whatifTab(body, equity) {
  const combos = equity.what_if.combos;
  const palette = equity.palette;
  const initial = combos[0].member_ids.filter(id => equity.algos.some(a => a.id === id));
  const st = { sel: new Set(initial), period: 'all', ymode: 'inr', search: '' };

  body.innerHTML = `
    <div class="controls" style="margin-bottom:12px">
      <div class="seg" id="wi-p"><span class="seg-label">Period</span><button data-p="all">All-time</button><button data-p="2026">2026</button></div>
      <div class="seg" id="wi-y"><span class="seg-label">Y</span><button data-y="inr">₹ / lot</button><button data-y="pts">Points</button></div>
      <button class="btn" id="wi-all">Add all</button>
      <button class="btn ghost" id="wi-clear">Clear</button>
    </div>
    <div id="wi-presets" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px"></div>
    <div style="display:grid;grid-template-columns:260px 1fr;gap:18px;align-items:start">
      <div class="card card-pad" style="max-height:580px;overflow:auto">
        <div class="eyebrow" style="margin-bottom:8px">Strategies</div>
        <input type="search" id="wi-search" placeholder="Filter…" style="width:100%;margin-bottom:8px">
        <div id="wi-list"></div>
      </div>
      <div>
        <div id="wi-note" class="note" style="margin-bottom:14px"></div>
        <div class="chart-frame"><div class="chart-canvas-wrap" style="height:440px"><canvas id="wi-canvas"></canvas></div></div>
        <div id="wi-score" style="margin-top:14px"></div>
        <div id="wi-detail" style="margin-top:18px"></div>
      </div>
    </div>`;

  const presets = () => { body.querySelector('#wi-presets').innerHTML =
    `<span class="seg-label">Quick combos</span>` + combos.map(c => `<button class="btn" data-combo="${c.id}">${escapeHtml(c.label)}</button>`).join(''); };
  const list = () => {
    const algos = equity.algos.filter(a => (a.short || a.name).toLowerCase().includes(st.search.toLowerCase()))
      .sort((x, y) => (y.total_pts || 0) - (x.total_pts || 0));
    body.querySelector('#wi-list').innerHTML = algos.map(a => `
      <label style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:.8rem;cursor:pointer">
        <input type="checkbox" data-wi="${a.id}" ${st.sel.has(a.id) ? 'checked' : ''}>
        <span class="swatch" style="background:${colorFor(a.id, 0, palette)}"></span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(a.short || a.name)}</span>
        <span class="mono muted" style="font-size:.68rem">${fmtPts(a.total_pts, false)}</span></label>`).join('');
  };
  const segs = () => {
    [...body.querySelectorAll('#wi-p button')].forEach(b => b.classList.toggle('active', b.dataset.p === st.period));
    [...body.querySelectorAll('#wi-y button')].forEach(b => b.classList.toggle('active', b.dataset.y === st.ymode));
  };
  const draw = () => { segs(); drawWhatifMulti(equity, st, palette); };

  presets(); list(); draw();

  const onClick = (e) => {
    const p = e.target.closest('#wi-p button'); if (p) { st.period = p.dataset.p; draw(); return; }
    const y = e.target.closest('#wi-y button'); if (y) { st.ymode = y.dataset.y; draw(); return; }
    const c = e.target.closest('button[data-combo]'); if (c) { const cb = combos.find(z => z.id === c.dataset.combo); st.sel = new Set(cb.member_ids); list(); draw(); return; }
    if (e.target.id === 'wi-all') { st.sel = new Set(equity.algos.map(a => a.id)); list(); draw(); return; }
    if (e.target.id === 'wi-clear') { st.sel.clear(); list(); draw(); return; }
  };
  const onChange = (e) => { const cb = e.target.closest('input[data-wi]'); if (cb) { cb.checked ? st.sel.add(cb.dataset.wi) : st.sel.delete(cb.dataset.wi); draw(); } };
  const onInput = (e) => { if (e.target.id === 'wi-search') { st.search = e.target.value; list(); } };
  body.addEventListener('click', onClick); body.addEventListener('change', onChange); body.addEventListener('input', onInput);
  cleanupFns.push(() => { body.removeEventListener('click', onClick); body.removeEventListener('change', onChange); body.removeEventListener('input', onInput); });
}

function drawWhatifMulti(equity, st, palette) {
  if (chart) { chart.destroy(); chart = null; }
  const ctx = document.getElementById('wi-canvas'); if (!ctx) return;
  const ids = [...st.sel].filter(id => equity.algos.some(a => a.id === id));
  const isInr = st.ymode === 'inr';
  const note = document.getElementById('wi-note');
  const scoreHost = document.getElementById('wi-score'), detailHost = document.getElementById('wi-detail');
  if (!ids.length) { note.innerHTML = 'Pick one or more strategies to combine (1 lot each).'; scoreHost.innerHTML = ''; detailHost.innerHTML = ''; return; }

  const solos = ids.map(id => {
    const a = equity.algos.find(z => z.id === id);
    const root = st.period === '2026' ? a.curves_2026 : a.curves;
    const pts = (root && root[`daily_${st.ymode}`]) || [];
    return { a, pts, color: colorFor(id, 0, palette), total: pts.length ? pts[pts.length - 1].y : 0 };
  });
  // combined = EQUAL-WEIGHT AVERAGE of daily P&L (÷N) over the union calendar —
  // i.e. capital split equally across the picks, so the line is comparable to a single strategy.
  const n = ids.length;
  const map = new Map();
  solos.forEach(s => s.pts.forEach(p => map.set(p.x, (map.get(p.x) || 0) + (p.day_pnl ?? 0))));
  const days = [...map.keys()].sort();
  let cum = 0;
  const combined = days.map(d => { cum += map.get(d) / n; return { x: d, y: cum }; });
  const combinedTotal = cum;

  const many = ids.length > 6;
  const datasets = solos.map(s => ({
    label: s.a.short || s.a.name, data: s.pts.map(p => ({ x: p.x, y: p.y })),
    borderColor: s.color, backgroundColor: s.color, borderWidth: many ? 1 : 1.6, pointRadius: 0, tension: 0.05,
  }));
  datasets.push({ label: 'Combined (avg)', data: combined, borderColor: '#B79CF0', backgroundColor: 'rgba(183,156,240,0.10)', borderWidth: 3, fill: true, pointRadius: 0, tension: 0.05 });

  chart = new Chart(ctx, {
    type: 'line', data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      scales: { x: { type: 'time', time: { tooltipFormat: 'dd MMM yyyy' }, ticks: { color: TICK, maxTicksLimit: 12 }, grid: { color: GRID } },
        y: { ticks: { color: TICK, callback: v => isInr ? '₹' + (v / 1000).toFixed(0) + 'k' : v }, grid: { color: GRID } } },
      plugins: { legend: { display: !many, position: 'bottom', labels: { color: '#C4BAA8', boxWidth: 12, font: { size: 10 } } } },
    },
  });

  const combos = equity.what_if.combos;
  const match = combos.find(c => c.member_ids.length === ids.length && c.member_ids.every(m => ids.includes(m)));
  note.innerHTML = match
    ? `<b>${escapeHtml(match.label)}.</b> ${escapeHtml(match.description || '')} <span class="muted">Combined = equal-weight average (÷${n}).</span>`
    : `<b>${ids.length} strateg${ids.length > 1 ? 'ies' : 'y'}, equal-weight average (÷${n})</b> — capital split evenly across the picks. Solo lines are each strategy on its own; the bold purple line is your blended equity, on the same scale as a single strategy.`;

  const fmt = isInr ? fmtLakh : fmtPts;
  const bestSolo = Math.max(...solos.map(s => s.total));
  scoreHost.innerHTML = scorecard([
    { label: 'Combined (avg)', value: fmt(combinedTotal), sm: true, cls: pnlClass(combinedTotal) },
    { label: 'Strategies', value: fmtNum(ids.length), sm: true },
    { label: 'Best solo', value: fmt(bestSolo), sm: true, cls: pnlClass(bestSolo) },
    { label: 'vs best solo', value: fmt(combinedTotal - bestSolo), sm: true, cls: pnlClass(combinedTotal - bestSolo) },
    { label: 'Trading days', value: fmtNum(days.length), sm: true },
  ]);

  const sorted = solos.slice().sort((a, b) => b.total - a.total);
  detailHost.innerHTML = `<div class="eyebrow" style="margin-bottom:10px">Contribution</div>
    <div class="table-wrap"><table class="data" style="font-size:.8rem"><thead><tr><th>Strategy</th><th class="num">Total</th><th class="num">Share</th></tr></thead><tbody>
      ${sorted.map(s => `<tr><td><span class="swatch" style="background:${s.color}"></span> ${escapeHtml(s.a.short || s.a.name)}</td>
        <td class="num ${pnlClass(s.total)}">${fmt(s.total)}</td>
        <td class="num muted">${combinedTotal ? Math.round(100 * s.total / combinedTotal) : 0}%</td></tr>`).join('')}
    </tbody></table></div>`;
}

/* ======================================================================
   TAB 3 — PORTFOLIO (equal-₹, 2026)
   ====================================================================== */
function portfolioTab(body, st_data, query) {
  if (!st_data) { body.innerHTML = `<div class="note">Portfolio data (option_buying_stratzy.json) unavailable.</div>`; return; }
  const algos = st_data.algos;
  const PRESET = ['6857f6a39edddcb829103b8f', '685848b09edddcb829103b9b', '6858551e9edddcb829103b9a']; // Prudent + Burst RR + Savdhaan (best-effort)
  const st = {
    selected: new Set((query && query.ids) ? query.ids.split(',') : algos.slice(0, 3).map(a => a.id)),
    invest: (query && +query.invest) || 100000,
    showSolo: true, showPort: true, search: '',
  };
  body.innerHTML = `
    <div style="display:grid;grid-template-columns:280px 1fr;gap:18px;align-items:start">
      <div class="card card-pad" style="max-height:660px;overflow:auto">
        <div class="eyebrow" style="margin-bottom:8px">Build a book</div>
        <input type="search" id="pf-search" placeholder="Filter…" style="width:100%;margin-bottom:8px">
        <div style="display:flex;gap:6px;margin-bottom:10px">
          <button class="btn" id="pf-all">All</button><button class="btn ghost" id="pf-clear">Clear</button>
        </div>
        <div id="pf-list"></div>
      </div>
      <div>
        <div class="controls" style="margin-bottom:12px">
          <label class="seg-label">₹ per algo</label>
          <input type="number" id="pf-invest" value="${st.invest}" min="10000" step="10000" style="width:130px">
          <label style="display:flex;align-items:center;gap:6px;font-size:.8rem"><input type="checkbox" id="pf-solo" checked> solo lines</label>
          <label style="display:flex;align-items:center;gap:6px;font-size:.8rem"><input type="checkbox" id="pf-port" checked> portfolio line</label>
        </div>
        <div id="pf-score" style="margin-bottom:14px"></div>
        <div class="chart-frame"><div class="chart-canvas-wrap" style="height:460px"><canvas id="pf-canvas"></canvas></div></div>
        <div id="pf-table" style="margin-top:18px"></div>
      </div>
    </div>`;

  const palette = ['#E8A33D', '#6FB4F2', '#46C68C', '#B79CF0', '#FB923C', '#F2615C', '#5FB3F0', '#2DC98F', '#F4B85C', '#CBB6F5', '#86efac', '#fbbf24', '#7ec8ff', '#f87171', '#c4b5fd'];

  // build 2026 daily cumulative-pct series per algo (additive day_pct)
  const seriesFor = (a) => {
    const tl = (a.performance.timeline_pct || []).filter(p => p.x >= '2026-01-01');
    let src = tl;
    if (!src.length) {
      const map = new Map(); (a.trades || []).forEach(t => { if (t.date >= '2026-01-01') map.set(t.date, (map.get(t.date) || 0) + (t.day_pct || 0)); });
      src = [...map.keys()].sort().map(d => ({ x: d, y: map.get(d) }));
    }
    let cum = 0;
    return src.map(p => ({ x: p.x, cumPct: (cum += p.y) }));
  };

  const draw = () => {
    renderList(); drawPortfolio();
  };
  const renderList = () => {
    const q = st.search.toLowerCase();
    document.getElementById('pf-list').innerHTML = algos
      .filter(a => (a.short || '').toLowerCase().includes(q))
      .map(a => `<label style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:.8rem;cursor:pointer">
        <input type="checkbox" data-pf="${a.id}" ${st.selected.has(a.id) ? 'checked' : ''}>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(a.short)}</span>
        <span class="mono muted" style="font-size:.7rem ">${fmtPts(a.summary.ytd_pts, false)}</span></label>`).join('');
  };
  const drawPortfolio = () => {
    if (chart) { chart.destroy(); chart = null; }
    const ctx = document.getElementById('pf-canvas'); if (!ctx) return;
    const picks = algos.filter(a => st.selected.has(a.id));
    const dayMap = new Map(); // date -> [equities]
    const perAlgo = picks.map((a, i) => {
      const ser = seriesFor(a);
      ser.forEach(p => {
        const eq = st.invest * (1 + p.cumPct / 100);
        if (!dayMap.has(p.x)) dayMap.set(p.x, []);
        dayMap.get(p.x).push(eq);
      });
      return { a, ser, color: palette[i % palette.length], data: ser.map(p => ({ x: p.x, y: st.invest * (1 + p.cumPct / 100) })) };
    });
    const days = [...dayMap.keys()].sort();
    const portData = days.map(d => ({ x: d, y: dayMap.get(d).reduce((s, v) => s + v, 0) / Math.max(1, picks.length) }));

    const ds = [];
    if (st.showSolo) perAlgo.forEach(p => ds.push({ label: p.a.short, data: p.data, borderColor: p.color, backgroundColor: p.color, borderWidth: 1.5, pointRadius: 0, tension: 0.05 }));
    if (st.showPort) ds.push({ label: 'Portfolio (avg)', data: portData, borderColor: '#F4EFE6', backgroundColor: 'rgba(244,239,230,0.06)', borderWidth: 3, fill: st.showPort, pointRadius: 0, tension: 0.05 });

    chart = new Chart(ctx, { type: 'line', data: { datasets: ds }, options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      scales: { x: { type: 'time', time: { tooltipFormat: 'dd MMM yyyy' }, ticks: { color: TICK, maxTicksLimit: 12 }, grid: { color: GRID } },
        y: { ticks: { color: TICK, callback: v => '₹' + (v / 1000).toFixed(0) + 'k' }, grid: { color: GRID } } },
      plugins: { legend: { position: 'bottom', labels: { color: '#C4BAA8', boxWidth: 12, font: { size: 10 } } } },
    } });

    // stats
    const rows = perAlgo.map(p => {
      const pnl = p.data.length ? p.data[p.data.length - 1].y - st.invest : 0;
      const dd = maxDrawdown(p.data.map(d => d.y));
      return { short: p.a.short, pnl, dd };
    }).sort((x, y) => y.pnl - x.pnl);
    const totDeployed = picks.length * st.invest;
    const portPnl = portData.length ? (portData[portData.length - 1].y - st.invest) : 0;
    const avgDd = rows.length ? rows.reduce((s, r) => s + r.dd, 0) / rows.length : 0;
    const best = rows[0];
    document.getElementById('pf-score').innerHTML = scorecard([
      { label: 'Portfolio P&L /algo', value: fmtLakh(portPnl), sm: true, cls: pnlClass(portPnl) },
      { label: 'Total deployed', value: fmtLakh(totDeployed), sm: true },
      { label: 'Avg max DD', value: fmtLakh(avgDd), sm: true, cls: 'neg' },
      { label: 'Best solo', value: best ? fmtLakh(best.pnl) : '—', sm: true, cls: best ? pnlClass(best.pnl) : '', delta: best ? escapeHtml(best.short) : '' },
    ]);
    document.getElementById('pf-table').innerHTML = `<div class="table-wrap"><table class="data"><thead><tr><th>Algo</th><th class="num">P&L /algo</th><th class="num">Max DD</th></tr></thead><tbody>
      ${rows.map(r => `<tr><td>${escapeHtml(r.short)}</td><td class="num ${pnlClass(r.pnl)}">${fmtLakh(r.pnl)}</td><td class="num neg">${fmtLakh(r.dd)}</td></tr>`).join('')}
      <tr style="border-top:2px solid var(--border-strong)"><td><b>Portfolio</b></td><td class="num ${pnlClass(portPnl)}"><b>${fmtLakh(portPnl)}</b></td><td class="num"></td></tr>
    </tbody></table></div>`;
  };

  const onClick = (e) => {
    if (e.target.id === 'pf-all') { algos.forEach(a => st.selected.add(a.id)); draw(); return; }
    if (e.target.id === 'pf-clear') { st.selected.clear(); draw(); return; }
  };
  const onChange = (e) => {
    const pf = e.target.closest('input[data-pf]'); if (pf) { pf.checked ? st.selected.add(pf.dataset.pf) : st.selected.delete(pf.dataset.pf); drawPortfolio(); return; }
    if (e.target.id === 'pf-invest') { st.invest = +e.target.value || 100000; drawPortfolio(); return; }
    if (e.target.id === 'pf-solo') { st.showSolo = e.target.checked; drawPortfolio(); return; }
    if (e.target.id === 'pf-port') { st.showPort = e.target.checked; drawPortfolio(); return; }
  };
  const onInput = (e) => { if (e.target.id === 'pf-search') { st.search = e.target.value; renderList(); } };
  body.addEventListener('click', onClick); body.addEventListener('change', onChange); body.addEventListener('input', onInput);
  cleanupFns.push(() => { body.removeEventListener('click', onClick); body.removeEventListener('change', onChange); body.removeEventListener('input', onInput); });
  draw();
}
