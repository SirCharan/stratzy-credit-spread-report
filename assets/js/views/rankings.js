// rankings.js — unified leaderboard (folds index + explore + option-buying overview).

import { load } from '../data.js';
import * as store from '../store.js';
import { sectionHead, controlRail, scorecard, bookTag, styleTag, openDrawer } from '../components.js';
import { fmtPts, fmtLakh, fmtInr, fmtPct, fmtNum, pnlClass, sparkSVG, escapeHtml, downloadCsv } from '../util.js';

let sort = { key: null, dir: -1 };  // key null → use store metric

export async function render(root) {
  const [explore, equity] = await Promise.all([load('explore_data'), load('equity_curves')]);
  const curveById = new Map(equity.algos.map(a => [a.id, a]));

  root.innerHTML = `<div class="fade-in">
    ${sectionHead('The leaderboard', 'What actually makes money',
      `Stratzy's cards quote a trailing return on capital. This recomputes every algo from its raw fills into the unit a NIFTY trader reads instinctively — <b>net premium points</b> and <b>₹ per one lot</b>. Rank by recent form, all-time, or Stratzy's own headline.`)}
    <div id="hero"></div>
    ${controlRail({})}
    <div id="score"></div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:8px">
      <button class="btn ghost" id="rank-csv">Export CSV</button>
      <button class="btn ghost" id="rank-density">Compact</button>
    </div>
    <div id="rank-table" style="margin-top:18px"></div>
    <p class="muted" style="margin-top:16px;font-size:.8rem">Click any row for a quick read, then open the full deep dive. ⚠ marks thin samples (&lt;20 trades) — treat those win rates as noise.</p>
  </div>`;

  const draw = () => {
    const list = computeRows(explore);
    paintHero(list, curveById);
    paintScore(list);
    paintTable(list, curveById);
  };
  draw();
  const unsub = store.subscribe(draw);

  const onClick = (e) => {
    const th = e.target.closest('th[data-key]');
    if (th) { const k = th.dataset.key; sort = { key: k, dir: sort.key === k ? -sort.dir : -1 }; draw(); return; }
    const tr = e.target.closest('tr[data-id]');
    if (tr && !e.target.closest('a')) openRow(tr.dataset.id, explore, curveById);
    if (e.target.id === 'rank-csv') {
      const list = computeRows(explore);
      downloadCsv('almanac-rankings.csv', list.map((r, i) => ({
        rank: i + 1, name: r.a.name, book: r.a.category, pts: r.pts, inr: r.inr, win_pct: r.wr, trades: r.trades, stratzy_1y: r.oneY,
      })));
    }
    if (e.target.id === 'rank-density') {
      const on = document.body.getAttribute('data-density') === 'compact';
      document.body.setAttribute('data-density', on ? '' : 'compact');
      e.target.textContent = on ? 'Compact' : 'Comfortable';
    }
  };
  root.addEventListener('click', onClick);
  return () => { unsub(); root.removeEventListener('click', onClick); };
}

// ---------- data shaping ----------
function metrics(a) {
  const p = store.get().period;
  const useAll = p === 'all';
  const grossPts = useAll ? (a.all_time_pts ?? 0) : (a.ytd_2026_pts ?? 0);
  const grossInr = useAll ? (a.all_time_inr ?? 0) : (a.ytd_2026_inr ?? 0);
  const wr = useAll ? a.all_time_wr : a.ytd_2026_wr;
  const trades = (useAll ? a.all_time_trades : a.ytd_2026_trades) ?? 0;
  const sortMetric = p === 'all' ? a.all_time_pts : p === '1y' ? a.one_year_pnl_pct : a.ytd_2026_pts;
  return {
    a, grossPts, trades, oneY: a.one_year_pnl_pct, wr: wr ?? 0,
    pts: store.netPts(grossPts, trades), inr: store.netInr(grossInr, trades),
    sortMetric: sortMetric ?? -1e9,
  };
}

function computeRows(explore) {
  const s = store.get();
  let list = explore.algos.slice();
  if (s.category !== 'all') list = list.filter(a => a.category === s.category);
  if (s.search) { const q = s.search.toLowerCase(); list = list.filter(a => (a.name + ' ' + a.short_name).toLowerCase().includes(q)); }
  list = list.map(metrics);
  const key = sort.key || 'sortMetric';
  const val = (r) => ({ pts: r.pts, inr: r.inr, wr: r.wr, trades: r.trades, oneY: r.oneY, name: r.a.name, sortMetric: r.sortMetric }[key]);
  list.sort((x, y) => {
    const a = val(x), b = val(y);
    if (typeof a === 'string') return -sort.dir * a.localeCompare(b);
    return sort.dir * ((a ?? -1e18) - (b ?? -1e18));
  });
  return list;
}

function curve(curveById, id) {
  const a = curveById.get(id); if (!a) return null;
  const root = store.get().period === '2026' ? a.curves_2026 : a.curves;
  return (root && root.daily_pts) || (a.curves && a.curves.daily_pts) || null;
}

// ---------- paints ----------
function paintHero(list, curveById) {
  const host = document.querySelector('#hero'); if (!host) return;
  const top = list[0];
  if (!top) { host.innerHTML = ''; return; }
  const c = curve(curveById, top.a.id);
  const spark = c ? sparkSVG(c, { w: 280, h: 70, color: top.grossPts >= 0 ? '#46C68C' : '#F2615C', fill: true }) : '';
  const bookNote = store.get().category !== 'all'
    ? ' · ' + (store.get().category === 'credit_spread' ? 'credit spreads' : 'option buying') : '';
  host.innerHTML = `
    <div class="card hero-split" style="margin:10px 0 22px;padding:26px 28px">
      <div>
        <div class="eyebrow" style="margin-bottom:10px">Lead story · ${escapeHtml(store.periodLabel())} #1${bookNote}</div>
        <div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap">
          <span class="hero-figure ${pnlClass(top.grossPts)}">${fmtPts(top.grossPts)}</span>
          <span class="muted" style="font-family:var(--mono);font-size:.82rem">points · ${fmtLakh(top.inr)} per lot</span>
        </div>
        <div style="margin-top:10px;font-family:var(--serif);font-size:1.45rem;letter-spacing:-.01em"><a href="#/algo/${top.a.id}">${escapeHtml(top.a.name)}</a></div>
        <div style="margin-top:9px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          ${bookTag(top.a.category)} ${styleTag(top.a.style, top.a.style_label)}
          <span class="chip">${fmtPct(top.wr)} win</span><span class="chip">${fmtNum(top.trades)} trades</span>
          <span class="chip">Stratzy 1Y ${fmtPct(top.oneY)}</span>
        </div>
        ${top.a.one_liner ? `<p class="muted" style="margin-top:12px;max-width:60ch;font-size:.9rem">${escapeHtml(top.a.one_liner)}</p>` : ''}
      </div>
      <div style="text-align:right">${spark}<div class="muted" style="font-family:var(--mono);font-size:.66rem;margin-top:6px">${escapeHtml(store.periodLabel())} equity · points</div></div>
    </div>`;
}

function paintScore(list) {
  const host = document.querySelector('#score'); if (!host) return;
  const pos = list.filter(r => r.grossPts > 0).length;
  const best = list[0];
  const wrs = list.map(r => r.wr).filter(x => x != null).sort((a, b) => a - b);
  const medWr = wrs.length ? wrs[Math.floor(wrs.length / 2)] : 0;
  host.innerHTML = scorecard([
    { label: 'In view', value: fmtNum(list.length), sm: true, delta: store.get().category === 'all' ? 'both books' : (store.get().category === 'credit_spread' ? 'credit spreads' : 'option buying') },
    { label: 'Profitable', value: `${pos}/${list.length}`, sm: true, deltaCls: pos >= list.length / 2 ? 'pos' : 'neg', delta: fmtPct(list.length ? 100 * pos / list.length : 0, 0) },
    { label: 'Median win rate', value: fmtPct(medWr), sm: true },
    { label: `Leader · ${store.periodLabel()}`, value: best ? fmtPts(best.grossPts) : '—', sm: true, cls: best ? pnlClass(best.grossPts) : '', delta: best ? escapeHtml(best.a.short_name) : '' },
  ]);
}

function paintTable(list, curveById) {
  const host = document.querySelector('#rank-table'); if (!host) return;
  const active = sort.key || 'sortMetric';
  const th = (key, label, cls = 'num') =>
    `<th class="${cls} ${active === key ? 'sorted' + (sort.dir === 1 ? ' asc' : '') : ''}" data-key="${key}">${label}</th>`;
  const pL = store.periodLabel();
  host.innerHTML = `
  <div class="table-wrap">
    <table class="data">
      <thead><tr>
        <th class="r ${active === 'sortMetric' ? 'sorted' : ''}" data-key="sortMetric">#</th>
        <th data-key="name">Algo</th>
        <th>Book</th>
        ${th('pts', `${pL} pts`)}
        ${th('inr', '₹ / lot')}
        ${th('wr', 'Win %')}
        ${th('trades', 'Trades')}
        ${th('oneY', 'Stratzy 1Y')}
        <th>Equity</th>
      </tr></thead>
      <tbody>${list.map((r, i) => row(r, i, curveById)).join('')}</tbody>
    </table>
  </div>`;
}

function row(r, i, curveById) {
  const c = curve(curveById, r.a.id);
  const spark = c ? sparkSVG(c, { w: 96, h: 26, color: r.grossPts >= 0 ? '#46C68C' : '#F2615C' }) : '';
  const thin = r.trades > 0 && r.trades < 20;
  const sub = r.a.short_name !== r.a.name ? r.a.short_name : (r.a.style_label || r.a.underlying || '');
  return `<tr data-id="${r.a.id}" class="clickable">
    <td class="rank-cell ${i < 3 ? 'top' : ''}">${i + 1}</td>
    <td class="name-cell">${escapeHtml(r.a.name)}${sub ? `<div class="sub">${escapeHtml(sub)}</div>` : ''}</td>
    <td>${bookTag(r.a.category)}</td>
    <td class="num ${pnlClass(r.grossPts)}">${fmtPts(r.pts)}</td>
    <td class="num">${fmtLakh(r.inr)}</td>
    <td class="num">${fmtPct(r.wr)}</td>
    <td class="num">${fmtNum(r.trades)} ${thin ? '<span class="tag tag-thin">⚠</span>' : ''}</td>
    <td class="num ${pnlClass(r.oneY)}">${fmtPct(r.oneY)}</td>
    <td>${spark}</td>
  </tr>`;
}

function openRow(id, explore, curveById) {
  const a = explore.algos.find(z => z.id === id); if (!a) return;
  const m = metrics(a);
  const c = curve(curveById, id);
  const spark = c ? sparkSVG(c, { w: 480, h: 92, color: m.grossPts >= 0 ? '#46C68C' : '#F2615C', fill: true }) : '';
  const kv = (k, v) => `<tr><td class="muted">${k}</td><td class="num" style="text-align:right">${v}</td></tr>`;
  openDrawer(`
    <div class="drawer-head">
      <div class="eyebrow" style="margin-bottom:8px">${a.category === 'credit_spread' ? 'Credit spread' : 'Option buying'} · ${escapeHtml(a.underlying || '')}</div>
      <h3 style="font-family:var(--serif);font-size:1.5rem;letter-spacing:-.01em">${escapeHtml(a.name)}</h3>
      ${a.one_liner ? `<p class="muted" style="margin-top:8px;font-size:.9rem">${escapeHtml(a.one_liner)}</p>` : ''}
    </div>
    <div class="drawer-body">
      <div style="margin-bottom:18px">${spark}</div>
      ${scorecard([
        { label: '2026 YTD pts', value: fmtPts(a.ytd_2026_pts), sm: true, cls: pnlClass(a.ytd_2026_pts) },
        { label: 'All-time pts', value: fmtPts(a.all_time_pts), sm: true, cls: pnlClass(a.all_time_pts) },
        { label: 'Stratzy 1Y', value: fmtPct(a.one_year_pnl_pct), sm: true, cls: pnlClass(a.one_year_pnl_pct) },
      ])}
      <div class="divider"></div>
      <table class="data" style="font-size:.8rem"><tbody>
        ${kv('All-time ₹ / lot', fmtInr(a.all_time_inr))}
        ${kv('All-time win rate', fmtPct(a.all_time_wr))}
        ${kv('All-time trades', fmtNum(a.all_time_trades))}
        ${kv('2026 ₹ / lot', fmtInr(a.ytd_2026_inr))}
        ${kv('2026 win rate', fmtPct(a.ytd_2026_wr))}
        ${kv('3M / 6M return', `${fmtPct(a.three_month_pnl_pct)} / ${fmtPct(a.six_month_pnl_pct)}`)}
        ${kv('Max drawdown', a.max_drawdown_pct != null ? fmtPct(a.max_drawdown_pct) : '—')}
        ${kv('Min capital', a.min_capital ? fmtInr(a.min_capital) : '—')}
        ${kv('CE / PE split', a.ce_pct != null ? `${fmtPct(a.ce_pct, 0)} / ${fmtPct(a.pe_pct, 0)}` : '—')}
      </tbody></table>
      <div style="margin-top:20px;display:flex;gap:10px;flex-wrap:wrap">
        <a class="btn primary" href="#/algo/${a.id}">Open full deep dive →</a>
        <a class="btn" href="#/charts">See on chart</a>
      </div>
    </div>`);
}
