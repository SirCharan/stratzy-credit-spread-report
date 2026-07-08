// compare.js — Compare & families view.
// Folds: compare.html + diff sections of explore.html + families/pairwise/heatmap/examples of option-buying.html.

import { load } from '../data.js';
import { sectionHead, scorecard } from '../components.js';
import { fmtPts, fmtPct, fmtNum, pnlClass, escapeHtml, heatCell } from '../util.js';

// ─── top-level book toggle (local state, not the global store) ───
let book = 'cs'; // 'cs' | 'ob'
let WR = new Map(); // algo name → explore_data row (for CS win-rate join)

// ─── heatmap filter local state ───
let csHmFilter = 'top10'; // 'top10' | 'all25' | 'overnight'
let obHmFilter = 'top10'; // 'top10' | 'top15' | 'all25'
let csExFilter = 'top10'; // 'top10' | 'all25'

// ─── expanded iron condor day rows ───
const sicExpanded = new Set();

// ─── module entry point ───
export async function render(root, params, query) {
  root.innerHTML = `<div class="loading">Loading compare data…</div>`;

  let diff, obDiff, explDiff, expl;
  try {
    [diff, obDiff, explDiff, expl] = await Promise.all([
      load('diff_data'),
      load('option_buying_diff'),
      load('explore_diff'),
      load('explore_data'),
    ]);
    WR = new Map((expl.algos ?? []).map(a => [a.name, a]));
  } catch (e) {
    root.innerHTML = `<div class="note"><b>Could not load compare data.</b> ${escapeHtml(String(e))}</div>`;
    return () => {};
  }

  // create tooltip div once
  const tip = document.createElement('div');
  tip.id = 'hm-tip';
  tip.style.cssText = [
    'position:fixed;z-index:200;pointer-events:none;display:none',
    'background:var(--surface-3);border:1px solid var(--border-strong)',
    'border-radius:var(--r-md);padding:8px 11px',
    'font-family:var(--mono);font-size:0.72rem;color:var(--ink-2)',
    'line-height:1.5;max-width:220px',
  ].join(';');
  document.body.appendChild(tip);

  const paint = () => {
    root.innerHTML = `<div class="fade-in">
      ${renderBookToggle()}
      <div id="book-body">
        ${book === 'cs' ? renderCS(diff, explDiff) : renderOB(obDiff, explDiff)}
      </div>
    </div>`;
  };

  paint();

  const onClick = (e) => {
    // book toggle
    const bookBtn = e.target.closest('[data-book]');
    if (bookBtn) { book = bookBtn.dataset.book; sicExpanded.clear(); paint(); return; }

    // heatmap filter buttons (cs)
    const csHm = e.target.closest('[data-cs-hm]');
    if (csHm) { csHmFilter = csHm.dataset.csHm; paint(); return; }

    // heatmap filter buttons (ob)
    const obHm = e.target.closest('[data-ob-hm]');
    if (obHm) { obHmFilter = obHm.dataset.obHm; paint(); return; }

    // examples filter buttons (cs)
    const csEx = e.target.closest('[data-cs-ex]');
    if (csEx) { csExFilter = csEx.dataset.csEx; paint(); return; }

    // iron condor day toggle
    const sicRow = e.target.closest('[data-sic-day]');
    if (sicRow) {
      const d = sicRow.dataset.sicDay;
      sicExpanded.has(d) ? sicExpanded.delete(d) : sicExpanded.add(d);
      paint(); return;
    }
  };

  const onMouseover = (e) => {
    const cell = e.target.closest('.hm-cell[data-tip]');
    if (!cell) { tip.style.display = 'none'; return; }
    tip.innerHTML = cell.dataset.tip;
    tip.style.display = 'block';
  };

  const onMousemove = (e) => {
    if (tip.style.display === 'none') return;
    const x = e.clientX + 14, y = e.clientY - 10;
    tip.style.left = Math.min(x, window.innerWidth - 240) + 'px';
    tip.style.top = Math.max(y, 4) + 'px';
  };

  const onMouseout = (e) => {
    if (!e.target.closest('.hm-cell[data-tip]')) return;
    tip.style.display = 'none';
  };

  root.addEventListener('click', onClick);
  root.addEventListener('mouseover', onMouseover);
  root.addEventListener('mousemove', onMousemove);
  root.addEventListener('mouseout', onMouseout);

  return () => {
    root.removeEventListener('click', onClick);
    root.removeEventListener('mouseover', onMouseover);
    root.removeEventListener('mousemove', onMousemove);
    root.removeEventListener('mouseout', onMouseout);
    tip.remove();
  };
}

// ─── book toggle ───
function renderBookToggle() {
  const btn = (val, label) =>
    `<button data-book="${val}" class="${book === val ? 'active' : ''}">${label}</button>`;
  return `<div style="margin-bottom:var(--s6)">
    <div class="seg" role="group">
      <span class="seg-label">View</span>
      ${btn('cs', 'Credit spreads')}
      ${btn('ob', 'Option buying')}
    </div>
  </div>`;
}

// ═══════════════════════════════════════════════════════════════
// CREDIT SPREADS BOOK
// ═══════════════════════════════════════════════════════════════

function renderCS(diff, explDiff) {
  const ladder = explDiff?.credit_spread?.stratzy_1y_ladder ?? [];
  return [
    sectionHead('Credit spreads', 'Strategy families & how they differ',
      'Twenty-five algos, one question: which signal, timing, and side-selection best captures overnight theta? These sections map the full family tree.'),
    renderCSFamilies(diff?.families ?? []),
    renderDecisionTree(diff?.decision_tree ?? []),
    renderCSHeatmap(diff?.calendars ?? {}),
    renderSyntheticIronCondor(diff?.synthetic_iron_condor),
    renderSameDayComparisons(diff?.same_day_comparisons ?? []),
    renderCSExamples(diff?.examples ?? {}),
    renderCSLadder(ladder),
  ].join('');
}

// § 1 — Strategy families
function renderCSFamilies(families) {
  if (!families.length) return '';
  return `<div class="section">
    <div class="eyebrow">Strategy families</div>
    <div class="grid" style="margin-top:var(--s4)">
      ${families.map(f => familyCard(f)).join('')}
    </div>
  </div>`;
}

function familyCard(f) {
  const rows = (f.members ?? []).map(m => {
    const w = WR.get(m.name);
    const wr = w?.ytd_2026_wr ?? w?.all_time_wr ?? w?.win_ratio_pct;
    return `<tr>
    <td class="name-cell">${escapeHtml(m.name ?? '—')}${m.short ? `<div class="sub">${escapeHtml(m.short)}</div>` : ''}</td>
    <td>${m.one_liner ? `<span class="muted" style="font-size:.78rem">${escapeHtml(m.one_liner)}</span>` : '—'}</td>
    <td class="num">${m.ce_pct != null ? fmtPct(m.ce_pct, 0) : '—'} / ${m.pe_pct != null ? fmtPct(m.pe_pct, 0) : '—'}</td>
    <td class="num">${m.trades_pm != null ? fmtNum(m.trades_pm, 1) : '—'}</td>
    <td class="num ${pnlClass(m.ytd_pts)}">${fmtPts(m.ytd_pts ?? null)}</td>
    <td class="num">${wr != null ? fmtPct(wr) : '—'}</td>
    <td class="num pos">${m.avg_win != null ? fmtPts(m.avg_win) : '—'}</td>
    <td class="num neg">${m.avg_loss != null ? fmtPts(m.avg_loss) : '—'}</td>
  </tr>`;
  }).join('');

  return `<div class="card">
    <div class="card-head">
      <h3>${escapeHtml(f.title ?? '')}</h3>
      ${f.subtitle ? `<span class="sub">${escapeHtml(f.subtitle)}</span>` : ''}
    </div>
    <div class="table-wrap" style="border:none;border-radius:0">
      <table class="data">
        <thead><tr>
          <th>Algo</th><th>Edge</th>
          <th class="num">CE% / PE%</th>
          <th class="num">Trades/mo</th>
          <th class="num">2026 pts</th>
          <th class="num">Win %</th>
          <th class="num">Avg win</th>
          <th class="num">Avg loss</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </div>`;
}

// § 2 — Decision tree
function renderDecisionTree(tree) {
  if (!tree.length) return '';
  const items = tree.map(node => {
    const answers = Object.entries(node.a ?? {}).map(([ans, result]) =>
      `<li style="margin-bottom:var(--s2)">
        <span style="color:var(--ink-2)">${escapeHtml(ans)}</span>
        <span class="muted"> → </span>
        <span style="font-family:var(--mono);font-size:.78rem;color:var(--gold)">${escapeHtml(result)}</span>
      </li>`
    ).join('');
    return `<div class="card card-pad" style="margin-bottom:var(--s3)">
      <p style="font-weight:600;margin-bottom:var(--s3)">${escapeHtml(node.q ?? '')}</p>
      <ul style="padding-left:var(--s4);list-style:none">${answers}</ul>
    </div>`;
  }).join('');

  return `<div class="section">
    <div class="eyebrow">Decision tree</div>
    <p class="muted" style="margin-bottom:var(--s4);font-size:.9rem">Three questions narrow your universe from 25 to the right handful.</p>
    ${items}
  </div>`;
}

// § 3 — P/L calendar heatmap (shared renderer)
function renderHeatmap(calendars, t1, t2, filterKeys, filterControls) {
  const algoKeys = filterKeys(Object.keys(calendars));
  if (!algoKeys.length) return `<p class="muted">No heatmap data.</p>`;

  const rows = algoKeys.map(name => {
    const cal = calendars[name] ?? {};
    const cells = (cal.cells ?? []).map(cell => {
      const cls = heatCell(cell.status, cell.pts, t1, t2);
      const noTrade = !cell.trades || cell.status === 'none' || cell.status === 'idle';
      const tipHtml = noTrade
        ? `<b>${escapeHtml(cal.short ?? name)}</b><br>${escapeHtml(cell.date ?? '')}<br>No trade`
        : `<b>${escapeHtml(cal.short ?? name)}</b><br>${escapeHtml(cell.date ?? '')}<br>${fmtPts(cell.pts)} pts · ${cell.trades} trade${cell.trades !== 1 ? 's' : ''}`;
      const safeAttr = tipHtml.replace(/"/g, '&quot;');
      return `<div class="hm-cell ${cls}" data-tip="${safeAttr}" style="cursor:default"></div>`;
    }).join('');
    const wl = `${cal.win_days ?? 0}W / ${cal.loss_days ?? 0}L`;
    return `<div class="hm-row">
      <div class="hm-label">${escapeHtml(cal.short ?? name)}<br><span class="st">${wl}</span></div>
      <div class="hm-cells">${cells}</div>
    </div>`;
  }).join('');

  return `${filterControls}<div style="overflow-x:auto;padding-bottom:4px">${rows}</div>
    <div class="hm-legend" style="margin-top:var(--s3)">
      <span>Less</span>
      <div class="hm-cell w1"></div><div class="hm-cell w2"></div><div class="hm-cell w3"></div><div class="hm-cell w4"></div>
      <span>Win</span>&nbsp;&nbsp;
      <div class="hm-cell l1"></div><div class="hm-cell l2"></div><div class="hm-cell l3"></div><div class="hm-cell l4"></div>
      <span>Loss</span>
    </div>`;
}

function renderCSHeatmap(calendars) {
  const allKeys = Object.keys(calendars);

  const filterFn = (keys) => {
    if (csHmFilter === 'top10') return keys.slice(0, 10);
    if (csHmFilter === 'overnight') return keys.filter(k => k.toLowerCase().includes('overnight') && !k.toLowerCase().includes('deep'));
    return keys; // all25
  };

  const mkBtn = (val, label) =>
    `<button data-cs-hm="${val}" class="${csHmFilter === val ? 'active' : ''}">${label}</button>`;
  const controls = `<div class="controls" style="margin-bottom:var(--s4)">
    <div class="seg" role="group">
      <span class="seg-label">Show</span>
      ${mkBtn('top10', 'Top 10')} ${mkBtn('all25', 'All 25')} ${mkBtn('overnight', 'Overnight only')}
    </div>
    <span class="muted" style="font-family:var(--mono);font-size:.7rem">${filterFn(allKeys).length} algos · hover for detail</span>
  </div>`;

  return `<div class="section">
    <div class="eyebrow">P/L calendar heatmap</div>
    <p class="muted" style="margin-bottom:var(--s4);font-size:.9rem">Each cell = one trading day. Green = win, red = loss. Intensity scales with magnitude (t1=${20}, t2=${50} pts).</p>
    <div class="card card-pad">
      ${renderHeatmap(calendars, 20, 50, filterFn, controls)}
    </div>
  </div>`;
}

// § 4 — Synthetic iron condor
function renderSyntheticIronCondor(sic) {
  if (!sic) return '';
  const s = sic.summary ?? {};
  const tiles = [
    { label: 'Net pts', value: fmtPts(s.net_pts), sm: true, cls: pnlClass(s.net_pts) },
    { label: 'Win days', value: fmtNum(s.win_days ?? 0), sm: true, cls: 'pos' },
    { label: 'Loss days', value: fmtNum(s.loss_days ?? 0), sm: true, cls: 'neg' },
    { label: 'Win rate', value: fmtPct(s.win_rate_pct), sm: true },
    { label: 'Avg combined', value: fmtPts(s.avg_combined_pts), sm: true },
    { label: 'Overlap %', value: fmtPct(s.overlap_pct_of_curvature ?? s.overlap_pct_of_iv_pe), sm: true },
  ];

  // single heatmap row for synthetic IC
  const calHtml = sic.calendar ? (() => {
    const cal = sic.calendar;
    const cells = (cal.cells ?? []).map(cell => {
      const cls = heatCell(cell.status, cell.pts, 20, 50);
      const noTrade = !cell.trades || cell.status === 'none';
      const tipHtml = noTrade
        ? `<b>${escapeHtml(cal.short ?? 'Synthetic IC')}</b><br>${escapeHtml(cell.date ?? '')}<br>No trade`
        : `<b>${escapeHtml(cal.short ?? 'Synthetic IC')}</b><br>${escapeHtml(cell.date ?? '')}<br>${fmtPts(cell.pts)} pts · ${cell.trades} trade${cell.trades !== 1 ? 's' : ''}`;
      return `<div class="hm-cell ${cls}" data-tip="${tipHtml.replace(/"/g, '&quot;')}" style="cursor:default"></div>`;
    }).join('');
    const wl = `${cal.win_days ?? 0}W / ${cal.loss_days ?? 0}L`;
    return `<div class="hm-row" style="margin:var(--s4) 0">
      <div class="hm-label">${escapeHtml(cal.short ?? 'Synthetic IC')}<br><span class="st">${wl}</span></div>
      <div class="hm-cells" style="overflow-x:auto">${cells}</div>
    </div>`;
  })() : '';

  const dayRows = (sic.days ?? []).map(day => {
    const isOpen = sicExpanded.has(day.date);
    const detailRow = isOpen ? `<tr class="detail-row" style="background:var(--surface-2)">
      <td colspan="4" style="padding:var(--s3) var(--s5)">
        <div style="display:flex;gap:var(--s5);flex-wrap:wrap">
          ${day.ce_trade ? `<div><span class="eyebrow" style="margin-bottom:var(--s2)">CE leg · ${escapeHtml(day.ce_spread ?? '')}</span>${tradeBox(day.ce_trade)}</div>` : ''}
          ${day.pe_trade ? `<div><span class="eyebrow" style="margin-bottom:var(--s2)">PE leg · ${escapeHtml(day.pe_spread ?? '')}</span>${tradeBox(day.pe_trade)}</div>` : ''}
        </div>
      </td>
    </tr>` : '';
    return `<tr data-sic-day="${escapeHtml(day.date)}" class="clickable">
      <td class="num">${escapeHtml(day.date ?? '')}</td>
      <td class="num ${pnlClass(day.combined_pts)}">${fmtPts(day.combined_pts)}</td>
      <td class="num ${pnlClass(day.ce_pts)}">${day.ce_pts != null ? fmtPts(day.ce_pts) : '—'}</td>
      <td class="num ${pnlClass(day.pe_pts)}">${day.pe_pts != null ? fmtPts(day.pe_pts) : '—'}</td>
    </tr>${detailRow}`;
  }).join('');

  return `<div class="section">
    <div class="eyebrow">Synthetic iron condor</div>
    <p class="muted" style="margin-bottom:var(--s4);font-size:.9rem">${escapeHtml(sic.description ?? '')}</p>
    ${scorecard(tiles)}
    ${calHtml}
    <div class="table-wrap" style="margin-top:var(--s4)">
      <table class="data">
        <thead><tr>
          <th class="num">Date</th>
          <th class="num">Combined pts</th>
          <th class="num">CE pts</th>
          <th class="num">PE pts</th>
        </tr></thead>
        <tbody>${dayRows}</tbody>
      </table>
    </div>
    <p class="muted" style="margin-top:var(--s3);font-size:.78rem">Click any row to expand CE/PE legs.</p>
  </div>`;
}

// § 5 — Same-day comparisons
function renderSameDayComparisons(comparisons) {
  if (!comparisons.length) return '';
  const cards = comparisons.map(comp => {
    const algoBoxes = Object.entries(comp.algos ?? {}).map(([name, trade]) => {
      const pts = trade.pts ?? null;
      return `<div style="flex:1;min-width:180px">
        <div class="eyebrow" style="margin-bottom:var(--s2)">${escapeHtml(name)}</div>
        ${tradeBox(trade)}
      </div>`;
    }).join('');
    return `<div class="card card-pad" style="margin-bottom:var(--s4)">
      <div style="display:flex;align-items:baseline;justify-content:space-between;gap:var(--s4);flex-wrap:wrap;margin-bottom:var(--s4)">
        <span class="eyebrow" style="margin-bottom:0">${escapeHtml(comp.date ?? '')}</span>
        <span class="chip">${escapeHtml(comp.label ?? '')}</span>
      </div>
      <div style="display:flex;gap:var(--s5);flex-wrap:wrap">${algoBoxes}</div>
    </div>`;
  }).join('');

  return `<div class="section">
    <div class="eyebrow">Same-day comparisons</div>
    <p class="muted" style="margin-bottom:var(--s4);font-size:.9rem">Same date, same market — different signals, different outcomes.</p>
    ${cards}
  </div>`;
}

// § 6 — Trade examples (CS)
function renderCSExamples(examples) {
  const allKeys = Object.keys(examples);
  if (!allKeys.length) return '';
  const filteredKeys = csExFilter === 'top10' ? allKeys.slice(0, 10) : allKeys;
  const mkBtn = (val, label) =>
    `<button data-cs-ex="${val}" class="${csExFilter === val ? 'active' : ''}">${label}</button>`;

  const cards = filteredKeys.map(name => {
    const ex = examples[name] ?? {};
    return `<div class="card">
      <div class="card-head">
        <h3>${escapeHtml(ex.short ?? name)}</h3>
        <a href="#/algo/${encodeURIComponent(name)}" style="font-size:.78rem">Deep dive →</a>
      </div>
      <div class="card-pad two-up">
        <div>
          <div class="eyebrow" style="margin-bottom:var(--s2);color:var(--gain)">Best win</div>
          ${ex.best_win ? tradeBox(ex.best_win) : '<span class="muted">—</span>'}
        </div>
        <div>
          <div class="eyebrow" style="margin-bottom:var(--s2);color:var(--loss)">Typical loss</div>
          ${ex.typical_loss ? tradeBox(ex.typical_loss) : '<span class="muted">—</span>'}
        </div>
      </div>
    </div>`;
  }).join('');

  return `<div class="section">
    <div class="eyebrow">Trade examples</div>
    <div class="controls" style="margin-bottom:var(--s4)">
      <div class="seg" role="group">
        <span class="seg-label">Show</span>
        ${mkBtn('top10', 'Top 10')} ${mkBtn('all25', 'All 25')}
      </div>
    </div>
    <div class="grid grid-auto">${cards}</div>
  </div>`;
}

// § 7 — CS Stratzy-1Y ladder
function renderCSLadder(ladder) {
  if (!ladder.length) return '';
  const cards = ladder.map(step => ladderCard(step)).join('');
  return `<div class="section">
    <div class="eyebrow">How adjacent algos differ — Stratzy 1Y ladder</div>
    <p class="muted" style="margin-bottom:var(--s4);font-size:.9rem">Step-by-step from the top Stratzy 1Y algo downward. One dimension changes at a time.</p>
    <div class="grid grid-auto">${cards}</div>
  </div>`;
}

// ═══════════════════════════════════════════════════════════════
// OPTION BUYING BOOK
// ═══════════════════════════════════════════════════════════════

function renderOB(obDiff, explDiff) {
  const ladder = explDiff?.option_buying?.stratzy_1y_ladder ?? [];
  return [
    sectionHead('Option buying', 'Families, signals & what separates them',
      'Twenty-five algos that purchase single CE or PE options intraday. The edge is in the entry signal and exit mechanic — not the instrument.'),
    renderOBFamilies(obDiff?.families ?? []),
    renderOBHeatmap(obDiff?.calendars ?? {}),
    renderOBExamples(obDiff?.examples ?? {}),
    renderOBLadder(ladder),
  ].join('');
}

// § OB-1 — Families
function renderOBFamilies(families) {
  if (!families.length) return '';
  return `<div class="section">
    <div class="eyebrow">Strategy families</div>
    <div class="grid" style="margin-top:var(--s4)">
      ${families.map(f => obFamilyCard(f)).join('')}
    </div>
  </div>`;
}

function obFamilyCard(f) {
  const memberRows = (f.members ?? []).map(m => `<tr>
    <td class="name-cell">${escapeHtml(m.name ?? '—')}${m.short && m.short !== m.name ? `<div class="sub">${escapeHtml(m.short)}</div>` : ''}</td>
    <td><span class="muted" style="font-size:.78rem">${escapeHtml(m.one_liner ?? '')}</span></td>
    <td class="num">${m.ce_pct != null ? fmtPct(m.ce_pct, 0) : '—'} / ${m.pe_pct != null ? fmtPct(m.pe_pct, 0) : '—'}</td>
    <td class="num ${pnlClass(m.ytd_pts)}">${fmtPts(m.ytd_pts ?? null)}</td>
    <td class="num ${pnlClass(m.all_pts)}">${fmtPts(m.all_pts ?? null)}</td>
    <td class="num">${m.win_rate != null ? fmtPct(m.win_rate) : '—'}</td>
  </tr>`).join('');

  const pairwiseCards = (f.pairwise ?? []).map(p => ladderCard(p)).join('');

  return `<div class="card" style="margin-bottom:var(--s5)">
    <div class="card-head">
      <h3>${escapeHtml(f.title ?? '')}</h3>
      ${f.subtitle ? `<span class="sub">${escapeHtml(f.subtitle)}</span>` : ''}
    </div>
    <div class="table-wrap" style="border:none;border-radius:0">
      <table class="data">
        <thead><tr>
          <th>Algo</th><th>Edge</th>
          <th class="num">CE% / PE%</th>
          <th class="num">2026 pts</th>
          <th class="num">All-time pts</th>
          <th class="num">Win %</th>
        </tr></thead>
        <tbody>${memberRows}</tbody>
      </table>
    </div>
    ${pairwiseCards ? `<div class="card-pad" style="border-top:1px solid var(--border)">
      <div class="eyebrow" style="margin-bottom:var(--s3)">Step-by-step pairwise</div>
      <div class="grid grid-auto">${pairwiseCards}</div>
    </div>` : ''}
  </div>`;
}

// § OB-2 — Heatmap
function renderOBHeatmap(calendars) {
  const allKeys = Object.keys(calendars);

  const filterFn = (keys) => {
    if (obHmFilter === 'top10') return keys.slice(0, 10);
    if (obHmFilter === 'top15') return keys.slice(0, 15);
    return keys; // all25
  };

  const mkBtn = (val, label) =>
    `<button data-ob-hm="${val}" class="${obHmFilter === val ? 'active' : ''}">${label}</button>`;
  const controls = `<div class="controls" style="margin-bottom:var(--s4)">
    <div class="seg" role="group">
      <span class="seg-label">Show</span>
      ${mkBtn('top10', 'Top 10')} ${mkBtn('top15', 'Top 15')} ${mkBtn('all25', 'All 25')}
    </div>
    <span class="muted" style="font-family:var(--mono);font-size:.7rem">${filterFn(allKeys).length} algos · hover for detail</span>
  </div>`;

  return `<div class="section">
    <div class="eyebrow">P/L calendar heatmap</div>
    <p class="muted" style="margin-bottom:var(--s4);font-size:.9rem">Each cell = one trading day. Intensity scales with magnitude (t1=${15}, t2=${40} pts).</p>
    <div class="card card-pad">
      ${renderHeatmap(calendars, 15, 40, filterFn, controls)}
    </div>
  </div>`;
}

// § OB-3 — Trade examples
function renderOBExamples(examples) {
  const keys = Object.keys(examples).slice(0, 12);
  if (!keys.length) return '';

  const cards = keys.map(name => {
    const ex = examples[name] ?? {};
    return `<div class="card">
      <div class="card-head">
        <h3>${escapeHtml(ex.short ?? name)}</h3>
        <a href="#/algo/${encodeURIComponent(name)}" style="font-size:.78rem">Deep dive →</a>
      </div>
      <div class="card-pad two-up">
        <div>
          <div class="eyebrow" style="margin-bottom:var(--s2);color:var(--gain)">Best win</div>
          ${ex.best_win ? obTradeBox(ex.best_win) : '<span class="muted">—</span>'}
        </div>
        <div>
          <div class="eyebrow" style="margin-bottom:var(--s2);color:var(--loss)">Typical loss</div>
          ${ex.typical_loss ? obTradeBox(ex.typical_loss) : '<span class="muted">—</span>'}
        </div>
      </div>
    </div>`;
  }).join('');

  return `<div class="section">
    <div class="eyebrow">Trade examples · first 12</div>
    <div class="grid grid-auto">${cards}</div>
  </div>`;
}

// § OB-4 — Stratzy-1Y ladder
function renderOBLadder(ladder) {
  if (!ladder.length) return '';
  const cards = ladder.map(step => ladderCard(step)).join('');
  return `<div class="section">
    <div class="eyebrow">How adjacent algos differ — Stratzy 1Y ladder</div>
    <p class="muted" style="margin-bottom:var(--s4);font-size:.9rem">Neighbouring algos on the Stratzy 1Y ranking. One dimension changes at a time.</p>
    <div class="grid grid-auto">${cards}</div>
  </div>`;
}

// ═══════════════════════════════════════════════════════════════
// SHARED HELPERS
// ═══════════════════════════════════════════════════════════════

// Credit-spread trade box (two-leg spread: sell + buy)
function tradeBox(trade) {
  if (!trade) return '';
  const pts = trade.pts ?? null;
  const sell = trade.sell ?? {};
  const buy = trade.buy ?? {};
  return `<div style="background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:var(--s3) var(--s4);font-family:var(--mono);font-size:.76rem">
    <div style="display:flex;justify-content:space-between;margin-bottom:var(--s2)">
      <span class="muted">${escapeHtml(trade.date ?? '')}</span>
      <span class="${pnlClass(pts)}">${fmtPts(pts)}</span>
    </div>
    <div style="margin-bottom:4px"><span class="chip" style="font-size:.64rem">${escapeHtml(trade.side ?? '')}</span></div>
    ${sell.sym ? `<div style="color:var(--ink-2)">Sell <b>${escapeHtml(sell.sym)}</b></div>
    <div class="muted" style="font-size:.7rem">entry ${sell.entry ?? '—'} → exit ${sell.exit ?? '—'}</div>` : ''}
    ${buy.sym ? `<div style="color:var(--ink-2);margin-top:3px">Buy <b>${escapeHtml(buy.sym)}</b></div>
    <div class="muted" style="font-size:.7rem">entry ${buy.entry ?? '—'} → exit ${buy.exit ?? '—'}</div>` : ''}
    ${trade.entry_credit != null ? `<div class="muted" style="margin-top:4px">Credit: ${fmtPts(trade.entry_credit)}</div>` : ''}
  </div>`;
}

// Option-buying trade box (single-leg: sym at top level)
function obTradeBox(trade) {
  if (!trade) return '';
  const pts = trade.pts ?? null;
  return `<div style="background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:var(--s3) var(--s4);font-family:var(--mono);font-size:.76rem">
    <div style="display:flex;justify-content:space-between;margin-bottom:var(--s2)">
      <span class="muted">${escapeHtml(trade.date ?? '')}</span>
      <span class="${pnlClass(pts)}">${fmtPts(pts)}</span>
    </div>
    <div style="margin-bottom:4px"><span class="chip" style="font-size:.64rem">${escapeHtml(trade.side ?? '')}</span></div>
    ${trade.sym ? `<div style="color:var(--ink-2)">Buy <b>${escapeHtml(trade.sym)}</b></div>
    <div class="muted" style="font-size:.7rem">entry ${trade.entry ?? '—'} → exit ${trade.exit ?? '—'}</div>` : ''}
    ${trade.entry_premium != null ? `<div class="muted" style="margin-top:4px">Premium: ${fmtPts(trade.entry_premium)}</div>` : ''}
  </div>`;
}

// Shared ladder/pairwise step card
function ladderCard(step) {
  const bullets = (step.bullets ?? []).map(b => `<li style="margin-bottom:4px">${escapeHtml(b)}</li>`).join('');
  const from = step.from_short ?? step.from ?? '';
  const to = step.to_short ?? step.to ?? '';
  return `<div class="card card-pad" style="margin-bottom:var(--s3)">
    <div style="display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap;margin-bottom:var(--s3)">
      <span class="chip">${escapeHtml(from)}</span>
      <span class="muted" style="font-family:var(--mono);font-size:.78rem">→</span>
      <span class="chip">${escapeHtml(to)}</span>
      ${step.shared_family ? `<span class="tag tag-muted">${escapeHtml(step.shared_family)}</span>` : ''}
    </div>
    <p style="font-weight:600;margin-bottom:var(--s3);font-size:.88rem">${escapeHtml(step.headline ?? '')}</p>
    ${bullets ? `<ul style="padding-left:var(--s4);font-size:.8rem;color:var(--ink-2)">${bullets}</ul>` : ''}
  </div>`;
}
