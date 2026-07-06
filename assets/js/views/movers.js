// movers.js — daily EOD 1-Month movers + "Your Book" overlay.
// Reads movers/latest.json (produced by generate_movers.py). No store dependency.

import { load } from '../data.js';
import { sectionHead, scorecard, openDrawer } from '../components.js';
import { fmtPct, fmtNum, fmtLakh, pnlClass, escapeHtml, fmtDate, sparkSVG } from '../util.js';

const CAT_COLORS = { 'Credit Spread': 'tag-cs', 'Option Buying': 'tag-ob' };
const catTag = c => `<span class="tag ${CAT_COLORS[c] || 'tag-muted'}">${escapeHtml(c || '—')}</span>`;
const star = f => (f ? '<span style="color:var(--gold)" title="in your research universe">★</span> ' : '');

// .pos / .neg auto-prepend ▲ / ▼ via CSS — pass magnitudes only, never a signed string.
function dRank(v) {
  if (v == null) return '<span class="muted">—</span>';
  if (v > 0) return `<span class="pos">${v}</span>`;
  if (v < 0) return `<span class="neg">${-v}</span>`;
  return '<span class="flat">·</span>';
}
function dPct(v) {
  if (v == null) return '<span class="muted">—</span>';
  if (v > 0) return `<span class="pos">${fmtPct(v, 1)}</span>`;
  if (v < 0) return `<span class="neg">${fmtPct(Math.abs(v), 1)}</span>`;
  return '<span class="flat">0.0%</span>';
}
const spark = s => (s && s.length > 1 ? sparkSVG(s, { w: 96, h: 26 }) : '<span class="muted">—</span>');

let sort = { key: 'rank', dir: 1 };  // dir 1 = asc (rank), -1 = desc

export async function render(root) {
  const d = await load('movers/latest');
  const byId = new Map(d.top.map(r => [r.id, r]));

  const editions = `edition <b>${fmtDate(d.generated_at)}</b>` +
    (d.prior_date ? ` · vs prior <b>${fmtDate(d.prior_date)}</b>` : '') +
    (d.week_ago_date ? ` · vs week <b>${fmtDate(d.week_ago_date)}</b>` : '');

  root.innerHTML = `<div class="fade-in">
    ${sectionHead('Daily movers', 'Who moved on 1-Month',
      `The top <b>25</b> of Stratzy's ${fmtNum(d.total_algos)} algos ranked by <b>1-Month return</b>, with day-on-day and week-on-week change in rank and return. ★ marks algos in the research universe. ${editions}.`)}
    ${d.narrative ? `<p class="note" style="margin:0 0 20px;max-width:70ch">${escapeHtml(d.narrative)}</p>` : ''}
    ${d.portfolio ? '<div id="m-book"></div>' : ''}
    <div id="m-score"></div>
    <div id="m-table" style="margin-top:18px"></div>
    <div id="m-lists" style="margin-top:22px"></div>
    <p class="muted" style="margin-top:16px;font-size:.78rem">1-Month return = Stratzy's headline <span class="chip">oneMonthPnl</span>. Prior/week deltas are reconstructed from each algo's rolling-return series on the first editions, then use captured daily snapshots. Trend = trailing 1-Month path.</p>
  </div>`;

  paintBook(d);
  paintScore(d);
  paintTable(d);
  paintLists(d);

  const onClick = e => {
    const th = e.target.closest('th[data-k]');
    if (th) { const k = th.dataset.k; sort.dir = sort.key === k ? -sort.dir : (k === 'rank' ? 1 : -1); sort.key = k; paintTable(d); return; }
    const tr = e.target.closest('tr[data-id]');
    if (tr && byId.has(tr.dataset.id)) openMover(byId.get(tr.dataset.id), d);
  };
  root.addEventListener('click', onClick);
  return () => root.removeEventListener('click', onClick);
}

// ---------- Your Book ----------
function paintBook(d) {
  const host = document.querySelector('#m-book'); if (!host || !d.portfolio) return;
  const p = d.portfolio;
  const nSlip = p.flags.length;
  const rowsHtml = p.holdings.map(h => `
    <tr data-id="${h.id}" class="clickable">
      <td class="name-cell">${escapeHtml(h.name)}${h.slipping ? ' <span class="tag tag-thin">slipping</span>' : ''}<div class="sub">${fmtLakh(h.allocated)} · ${h.weight_pct != null ? h.weight_pct + '%' : '—'} of book</div></td>
      <td class="num">${h.rank != null ? '#' + h.rank : '—'}</td>
      <td class="num ${pnlClass(h.one_month_pnl)}">${fmtPct(h.one_month_pnl)}</td>
      <td class="num">${dRank(h.dod_rank_delta)}</td>
      <td class="num">${dPct(h.dod_pnl_delta)}</td>
      <td class="num">${dRank(h.wow_rank_delta)}</td>
      <td class="num ${pnlClass(h.seven_day_pnl)}">${fmtPct(h.seven_day_pnl)}</td>
      <td>${spark(h.spark)}</td>
    </tr>`).join('');
  host.innerHTML = `
    <div class="card" style="margin:6px 0 24px;padding:20px 22px">
      <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:12px;margin-bottom:14px">
        <div class="eyebrow">Your book · ${p.holdings.length} algos</div>
        <div class="muted" style="font-family:var(--mono);font-size:.8rem">
          ${fmtLakh(p.total_allocated)} allocated · weighted 1M
          <b class="${pnlClass(p.weighted_1m)}">${fmtPct(p.weighted_1m)}</b>
          ${nSlip ? ` · <span class="neg">${nSlip} slipping</span>` : ' · <span class="pos">all holding up</span>'}
        </div>
      </div>
      <div class="table-wrap"><table class="data"><thead><tr>
        <th>Holding</th><th class="num">Rank</th><th class="num">1M %</th>
        <th class="num">DoD Δrk</th><th class="num">DoD Δ1M</th><th class="num">WoW Δrk</th>
        <th class="num">7D %</th><th>Trend</th>
      </tr></thead><tbody>${rowsHtml}</tbody></table></div>
    </div>`;
}

// ---------- scorecard ----------
function paintScore(d) {
  const host = document.querySelector('#m-score'); if (!host) return;
  const up = d.risers[0], dn = d.fallers[0];
  host.innerHTML = scorecard([
    { label: 'Biggest riser', value: up ? fmtPct(up.dod_pnl_delta, 1, true) : '—', sm: true, cls: 'pos', delta: up ? escapeHtml(up.name.slice(0, 24)) : '' },
    { label: 'Biggest faller', value: dn ? fmtPct(dn.dod_pnl_delta, 1, true) : '—', sm: true, cls: 'neg', delta: dn ? escapeHtml(dn.name.slice(0, 24)) : '' },
    { label: 'Entered top-25', value: fmtNum(d.entered.length), sm: true, delta: `${d.exited.length} exited` },
    { label: 'Edition', value: fmtDate(d.generated_at), sm: true, delta: 'daily EOD' },
  ]);
}

// ---------- top-25 table ----------
function sortedTop(d) {
  const list = d.top.slice();
  const k = sort.key;
  list.sort((x, y) => sort.dir * (((x[k] ?? -1e9)) - ((y[k] ?? -1e9))));
  return list;
}
function paintTable(d) {
  const host = document.querySelector('#m-table'); if (!host) return;
  const th = (k, l, cls = 'num') => `<th class="${cls} ${sort.key === k ? 'sorted' + (sort.dir === 1 ? ' asc' : '') : ''}" data-k="${k}">${l}</th>`;
  host.innerHTML = `
  <div class="table-wrap"><table class="data"><thead><tr>
    ${th('rank', '#', 'r')}
    <th>Algo</th><th>Category</th>
    ${th('one_month_pnl', '1M %')}
    ${th('dod_rank_delta', 'DoD Δrank')}
    ${th('dod_pnl_delta', 'DoD Δ1M')}
    ${th('wow_rank_delta', 'WoW Δrank')}
    ${th('wow_pnl_delta', 'WoW Δ1M')}
    ${th('seven_day_pnl', '7D %')}
    <th>Trend</th>
  </tr></thead><tbody>
    ${sortedTop(d).map(r => `<tr data-id="${r.id}" class="clickable">
      <td class="rank-cell ${r.rank <= 3 ? 'top' : ''}">${r.rank}</td>
      <td class="name-cell">${star(r.in_research)}${escapeHtml(r.name)}<div class="sub">${escapeHtml(r.underlying || '')}</div></td>
      <td>${catTag(r.display_category)}</td>
      <td class="num ${pnlClass(r.one_month_pnl)}">${fmtPct(r.one_month_pnl)}</td>
      <td class="num">${dRank(r.dod_rank_delta)}</td>
      <td class="num">${dPct(r.dod_pnl_delta)}</td>
      <td class="num">${dRank(r.wow_rank_delta)}</td>
      <td class="num">${dPct(r.wow_pnl_delta)}</td>
      <td class="num ${pnlClass(r.seven_day_pnl)}">${fmtPct(r.seven_day_pnl)}</td>
      <td>${spark(r.spark)}</td>
    </tr>`).join('')}
  </tbody></table></div>`;
}

// ---------- risers / fallers / entered / exited ----------
function miniList(title, items, render) {
  if (!items || !items.length) return `<div class="card" style="padding:16px 18px"><div class="eyebrow" style="margin-bottom:8px">${title}</div><p class="muted" style="font-size:.82rem">—</p></div>`;
  return `<div class="card" style="padding:16px 18px"><div class="eyebrow" style="margin-bottom:10px">${title}</div>
    <table class="data" style="font-size:.82rem"><tbody>${items.map(render).join('')}</tbody></table></div>`;
}
function paintLists(d) {
  const host = document.querySelector('#m-lists'); if (!host) return;
  const nm = r => `${star(r.in_research)}${escapeHtml(r.name)}`;
  host.innerHTML = `<div class="movers-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px">
    ${miniList('Biggest risers · day', d.risers, r => `<tr><td>${nm(r)}</td><td class="num">${dPct(r.dod_pnl_delta)}</td><td class="num">${dRank(r.dod_rank_delta)}</td></tr>`)}
    ${miniList('Biggest fallers · day', d.fallers, r => `<tr><td>${nm(r)}</td><td class="num">${dPct(r.dod_pnl_delta)}</td><td class="num">${dRank(r.dod_rank_delta)}</td></tr>`)}
    ${miniList('Entered top-25', d.entered, r => `<tr><td>${escapeHtml(r.name)}</td><td class="num">#${r.rank}</td><td class="num ${pnlClass(r.one_month_pnl)}">${fmtPct(r.one_month_pnl)}</td></tr>`)}
    ${miniList('Dropped out of top-25', d.exited, r => `<tr><td>${escapeHtml(r.name)}</td><td class="num muted">was #${r.prior_rank}</td></tr>`)}
  </div>`;
}

// ---------- drawer ----------
function openMover(r, d) {
  const kv = (k, v) => `<tr><td class="muted">${k}</td><td class="num" style="text-align:right">${v}</td></tr>`;
  const big = r.spark && r.spark.length > 1 ? sparkSVG(r.spark, { w: 480, h: 92, fill: true }) : '';
  openDrawer(`
    <div class="drawer-head">
      <div class="eyebrow" style="margin-bottom:8px">${escapeHtml(r.display_category || '')} · ${escapeHtml(r.underlying || '')} · rank #${r.rank}</div>
      <h3 style="font-family:var(--serif);font-size:1.5rem;letter-spacing:-.01em">${star(r.in_research)}${escapeHtml(r.name)}</h3>
    </div>
    <div class="drawer-body">
      ${big ? `<div style="margin-bottom:16px">${big}<div class="muted" style="font-family:var(--mono);font-size:.66rem;margin-top:6px">Trailing 1-Month return · %</div></div>` : ''}
      ${scorecard([
        { label: '1-Month', value: fmtPct(r.one_month_pnl), sm: true, cls: pnlClass(r.one_month_pnl) },
        { label: '7-Day', value: fmtPct(r.seven_day_pnl), sm: true, cls: pnlClass(r.seven_day_pnl) },
        { label: 'Win %', value: fmtPct(r.win_ratio), sm: true },
      ])}
      <div class="divider"></div>
      <table class="data" style="font-size:.82rem"><tbody>
        ${kv('Rank today', '#' + r.rank)}
        ${kv(`Day-on-day (vs ${fmtDate(d.prior_date)})`, `${dRank(r.dod_rank_delta)} rank · ${dPct(r.dod_pnl_delta)}`)}
        ${kv(`Week-on-week (vs ${fmtDate(d.week_ago_date)})`, `${dRank(r.wow_rank_delta)} rank · ${dPct(r.wow_pnl_delta)}`)}
        ${kv('In research universe', r.in_research ? '★ yes' : 'no')}
      </tbody></table>
    </div>`);
}
