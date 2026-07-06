// regime.js (view) — "When does each strategy make money?" attribution across Nifty market regimes.
// Direction (trailing 20d Nifty move) × realized volatility (trailing 20d, terciles), tagged at trade exit.

import { load } from '../data.js';
import { sectionHead, bookTag } from '../components.js';
import { fmtPts, fmtPct, fmtNum, pnlClass, escapeHtml } from '../util.js';
import { buildNiftyRegime, attributeStrategy, DIRS, VOLS } from '../regime.js';

let cleanups = [];
function teardown() { cleanups.forEach(f => { try { f(); } catch {} }); cleanups = []; }

const DIR_LABEL = { bull: 'Bull', sideways: 'Sideways', bear: 'Bear' };
const VOL_LABEL = { low: 'Low vol', normal: 'Normal', high: 'High vol' };
const DIR_COLOR = { bull: '#46C68C', sideways: '#8A8070', bear: '#F2615C' };

function heatBg(v, max) {
  if (!v || !max) return 'var(--surface-2)';
  const a = Math.min(Math.abs(v) / max, 1) * 0.55;
  return v >= 0 ? `rgba(70,198,140,${a})` : `rgba(242,97,92,${a})`;
}

export async function render(root, params, query) {
  const [equity, nifty] = await Promise.all([load('equity_curves'), load('nifty_daily')]);
  const regime = buildNiftyRegime(nifty);

  // attribute every algo that has trade-level data
  const rows = equity.algos
    .filter(a => (a.curves || {}).trade_pts && a.curves.trade_pts.length)
    .map(a => ({ a, attr: attributeStrategy(a.curves.trade_pts, regime) }))
    .sort((x, y) => y.a.total_pts - x.a.total_pts);
  const byId = new Map(rows.map(r => [r.a.id, r]));

  const st = { cat: (query && query.cat) || 'all', sel: (query && query.algo) || rows[0]?.a.id };

  root.innerHTML = `<div class="fade-in">
    ${sectionHead('The regime desk', 'When does each strategy actually make money?',
      `Every trade is tagged by the Nifty regime on its exit day — <b>direction</b> (trailing 20-day move: ≥+2% bull, ≤−2% bear, else sideways) and <b>realized volatility</b> (trailing 20-day, split into terciles, a local stand-in for IV). Read across to see which conditions a strategy needs to print, and which quietly bleed it.`)}
    <div id="rg-ribbon" style="margin:6px 0 22px"></div>
    <div class="seg" id="rg-cat" style="margin-bottom:16px">
      <span class="seg-label">Book</span>
      <button data-cat="all">All</button><button data-cat="credit_spread">Credit spreads</button><button data-cat="option_buying">Option buying</button>
    </div>
    <div id="rg-matrix" style="margin-bottom:24px"></div>
    <div class="card"><div class="card-head"><h3>All strategies · avg pts / trade by regime</h3><span class="sub">click a row to load its edge matrix</span></div>
      <div class="card-pad" style="overflow:auto" id="rg-table"></div></div>
    <p class="muted" style="font-size:.72rem;margin-top:14px">Exit-date tagging is exact for ~overnight credit spreads; for multi-day option-buying holds it approximates the regime over the hold. Volatility here is <b>realized</b> Nifty vol, not India VIX — see the roadmap for adding true implied vol.</p>
  </div>`;

  // ---- Nifty regime ribbon ----
  const ribbon = () => {
    const cells = regime.dates.map(d => { const r = regime.map.get(d); return `<div title="${d} · ${DIR_LABEL[r.dir]} · ${VOL_LABEL[r.vol]}" style="flex:1;min-width:1px;height:18px;background:${DIR_COLOR[r.dir]};opacity:${r.vol === 'high' ? 1 : r.vol === 'normal' ? 0.66 : 0.4}"></div>`; }).join('');
    root.querySelector('#rg-ribbon').innerHTML =
      `<div class="eyebrow" style="margin-bottom:6px">Nifty regime timeline · ${regime.dates[0]} → ${regime.dates[regime.dates.length - 1]}</div>
       <div style="display:flex;gap:0;border-radius:6px;overflow:hidden;border:1px solid var(--border)">${cells}</div>
       <div style="display:flex;gap:16px;margin-top:8px;font-size:.7rem" class="muted">
         <span><span class="swatch" style="background:${DIR_COLOR.bull}"></span> Bull</span>
         <span><span class="swatch" style="background:${DIR_COLOR.sideways}"></span> Sideways</span>
         <span><span class="swatch" style="background:${DIR_COLOR.bear}"></span> Bear</span>
         <span style="margin-left:auto">opacity = volatility (faint low → solid high)</span></div>`;
  };

  // ---- 3×3 edge matrix for the selected strategy ----
  const matrix = () => {
    const row = byId.get(st.sel) || rows[0]; if (!row) return;
    const { a, attr } = row;
    const max = Math.max(...DIRS.flatMap(d => VOLS.map(v => Math.abs(attr.cross[`${d}_${v}`].avg_pts))), 1);
    const head = `<tr><th></th>${VOLS.map(v => `<th class="num">${VOL_LABEL[v]}</th>`).join('')}<th class="num">All dir</th></tr>`;
    const body = DIRS.map(d => `<tr><td style="font-weight:600;color:${DIR_COLOR[d]}">${DIR_LABEL[d]}</td>
      ${VOLS.map(v => { const c = attr.cross[`${d}_${v}`]; return `<td class="num" style="background:${heatBg(c.avg_pts, max)};border-radius:6px">
        <div class="mono ${pnlClass(c.avg_pts)}" style="font-size:.95rem">${c.trades ? fmtPts(c.avg_pts) : '·'}</div>
        <div class="muted" style="font-size:.62rem">${c.trades ? `${fmtNum(c.trades)}t · ${fmtPct(c.win_rate)}` : '—'}</div></td>`; }).join('')}
      <td class="num"><div class="mono ${pnlClass(attr.dir[d].avg_pts)}">${attr.dir[d].trades ? fmtPts(attr.dir[d].avg_pts) : '·'}</div>
        <div class="muted" style="font-size:.62rem">${fmtNum(attr.dir[d].trades)}t</div></td></tr>`).join('');
    const foot = `<tr><td class="muted">All vol</td>${VOLS.map(v => `<td class="num"><div class="mono ${pnlClass(attr.vol[v].avg_pts)}">${attr.vol[v].trades ? fmtPts(attr.vol[v].avg_pts) : '·'}</div><div class="muted" style="font-size:.62rem">${fmtNum(attr.vol[v].trades)}t</div></td>`).join('')}
      <td class="num"><div class="mono ${pnlClass(attr.overall.totalPts)}">${fmtPts(attr.overall.totalPts)}</div><div class="muted" style="font-size:.62rem">${fmtNum(attr.overall.trades)}t</div></td></tr>`;
    root.querySelector('#rg-matrix').innerHTML = `
      <div class="card"><div class="card-head"><h3>${escapeHtml(a.short || a.name)} · edge matrix</h3>${bookTag(a.category)}
        <span class="sub">${fmtNum(attr.overall.trades)} trades · ${fmtPct(attr.overall.winRate)} WR · PF ${attr.overall.profitFactor === Infinity ? '∞' : attr.overall.profitFactor.toFixed(2)}</span></div>
        <div class="card-pad" style="overflow:auto"><table class="data" style="font-size:.82rem;text-align:center"><thead>${head}</thead><tbody>${body}${foot}</tbody></table>
        <p class="muted" style="font-size:.7rem;margin-top:8px">Avg pts / trade. Green = profitable in that regime, red = loses. Cell tint scales with magnitude.</p></div></div>`;
  };

  // ---- comparison table ----
  const table = () => {
    const list = rows.filter(r => st.cat === 'all' ? true : r.a.category === st.cat);
    const cell = b => `<td class="num ${pnlClass(b.avg_pts)}">${b.trades ? fmtPts(b.avg_pts) : '—'}</td>`;
    root.querySelector('#rg-table').innerHTML = `<table class="data" style="font-size:.78rem"><thead><tr>
      <th>Strategy</th><th>Book</th><th class="num">Bull</th><th class="num">Side</th><th class="num">Bear</th>
      <th class="num">Low vol</th><th class="num">Normal</th><th class="num">High vol</th><th class="num">Total pts</th></tr></thead><tbody>
      ${list.map(({ a, attr }) => `<tr data-algo="${a.id}" style="cursor:pointer${a.id === st.sel ? ';background:var(--surface-2)' : ''}">
        <td>${escapeHtml(a.short || a.name)}</td><td>${bookTag(a.category)}</td>
        ${cell(attr.dir.bull)}${cell(attr.dir.sideways)}${cell(attr.dir.bear)}
        ${cell(attr.vol.low)}${cell(attr.vol.normal)}${cell(attr.vol.high)}
        <td class="num ${pnlClass(a.total_pts)}">${fmtPts(a.total_pts)}</td></tr>`).join('')}
    </tbody></table>`;
  };

  ribbon(); matrix(); table();
  const onClick = e => {
    const c = e.target.closest('#rg-cat button'); if (c) { st.cat = c.dataset.cat; [...root.querySelectorAll('#rg-cat button')].forEach(b => b.classList.toggle('active', b.dataset.cat === st.cat)); table(); return; }
    const r = e.target.closest('tr[data-algo]'); if (r) { st.sel = r.dataset.algo; matrix(); table(); }
  };
  root.addEventListener('click', onClick);
  [...root.querySelectorAll('#rg-cat button')].forEach(b => b.classList.toggle('active', b.dataset.cat === st.cat));
  cleanups.push(() => root.removeEventListener('click', onClick));
  return teardown;
}
