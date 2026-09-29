// selector.js — the daily selector: today's regime + deploy/copy/drop eligibility across the book.
// Data: selector.json (eager) + regime_panel.json (lazy, only for the per-algo heatmap).

import { load } from '../data.js';
import { sectionHead, scorecard } from '../components.js';
import { fmtInr, fmtPct, fmtNum, fmtDate, escapeHtml } from '../util.js';

const CAT_TAG = {
  'Credit Spread': 'tag-cs', 'Option Buying': 'tag-ob',
  'Short Straddle': 'tag-muted', 'Short Strangle': 'tag-muted',
};
const catTag = c => `<span class="tag ${CAT_TAG[c] || 'tag-muted'}">${escapeHtml(c || '—')}</span>`;

const biasCls = b => b === 'bullish' ? 'pos' : b === 'bearish' ? 'neg' : 'flat';

const VERDICT_STYLE = {
  favourable:   ['var(--gain-dim)', 'var(--gain)'],
  mixed:        ['var(--gold-wash)', 'var(--gold-hi)'],
  unfavourable: ['var(--loss-dim)', 'var(--loss)'],
};
function verdictTag(v) {
  const [bg, fg] = VERDICT_STYLE[v] || ['var(--surface-3)', 'var(--ink-2)'];
  return `<span class="tag" style="background:${bg};color:${fg}">${escapeHtml(v || '—')}</span>`;
}
function scoreTag(eligible, score) {
  const cls = eligible ? 'pos' : 'flat';
  return `<span class="${cls} mono" style="font-size:.78rem;font-weight:600">${score != null ? score.toFixed(0) : '—'}</span>`;
}
function reasonLine(r) {
  const pass = r.startsWith('PASS');
  const txt = r.replace(/^PASS |^FAIL /, '');
  return `<div class="${pass ? 'pos' : 'neg'}" style="font-size:.78rem;padding:2px 0">${escapeHtml(txt)}</div>`;
}

const TREND_LABEL = { bull: 'Bull', side: 'Sideways', bear: 'Bear' };
const DTE_LABEL = { '0': 'Expiry (0 DTE)', '1': '1 DTE', '3+': '3+ DTE' };
const DIM_LABEL = { trend_20d: 'Trend', vix_tercile: 'VIX', iv_rank_tercile: 'IV rank', skew_sign: 'Skew', dte_bucket: 'DTE' };
const DIM_BUCKETS = {
  trend_20d: ['bull', 'side', 'bear'],
  vix_tercile: ['low', 'mid', 'high'],
  iv_rank_tercile: ['low', 'mid', 'high'],
  skew_sign: ['negative', 'flat', 'positive'],
  dte_bucket: ['0', '1', '3+'],
};
const BUCKET_LABEL = {
  bull: 'Bull', side: 'Side', bear: 'Bear', low: 'Low', mid: 'Mid', high: 'High',
  negative: 'Neg', flat: 'Flat', positive: 'Pos', '0': '0d', '1': '1d', '3+': '3d+',
};
function heatBg(v, max) {
  if (v == null || !max) return 'var(--surface-2)';
  const a = Math.min(Math.abs(v) / max, 1) * 0.55;
  return v >= 0 ? `rgba(70,198,140,${a.toFixed(2)})` : `rgba(242,97,92,${a.toFixed(2)})`;
}

let PANEL_BY_ID = null; // lazily-loaded regime_panel.json, indexed
async function panelFor(id) {
  if (!PANEL_BY_ID) {
    const rp = await load('regime_panel');
    PANEL_BY_ID = new Map(rp.algos.map(a => [a.id, a]));
  }
  return PANEL_BY_ID.get(id) || null;
}

function flatten(sel) {
  return sel.algos.map(a => ({
    id: a.id, name: a.name, category: a.category, structure: a.structure, bias: a.bias,
    in_book: a.in_book, rationale: a.rationale,
    trades: a.metrics.trades, wr: a.metrics.wr, pf: a.metrics.pf_inf ? Infinity : a.metrics.pf,
    calmar: a.metrics.calmar, margin_per_lot: a.metrics.margin_per_lot, corr_to_book: a.metrics.corr_to_book,
    verdict: a.fit_today.verdict,
    deploy_score: a.deploy.score, deploy_eligible: a.deploy.eligible, deploy_reasons: a.deploy.reasons,
    copy_score: a.copy.score, copy_eligible: a.copy.eligible, copy_reasons: a.copy.reasons,
  }));
}

let st = { sort: 'deploy_score', dir: -1, search: '', fitsOnly: false, sel: null, expanded: null };

export async function render(root, params, query) {
  const sel = await load('selector');
  const byId = new Map(sel.algos.map(a => [a.id, a]));
  const ROWS = flatten(sel);
  st.sel = st.sel && byId.has(st.sel) ? st.sel : (sel.shortlist.deploy[0] || sel.algos[0]?.id);
  st.expanded = null;

  const t = sel.today;
  root.innerHTML = `<div class="fade-in">
    ${sectionHead('The selector', 'What fits today',
      `<b>${sel.counts.algos}</b> in-scope algos scored against today's regime, as of the <b>${fmtDate(t.as_of_market_close)}</b> close. IV terciles lag to <b>${fmtDate(t.iv_as_of)}</b> (bhavcopy publish delay). <b>${sel.counts.deploy_eligible}</b> clear the deploy gates, <b>${sel.counts.copy_eligible}</b> clear the copy gates.`)}

    <div id="sel-strip" style="margin-bottom:36px"></div>

    <div class="section" id="sel-deploy"></div>
    <div class="section" id="sel-copy"></div>
    <div class="section" id="sel-drop"></div>

    <div class="section">
      <div class="section-head" style="margin-bottom:16px">
        <div class="eyebrow">The full board</div>
        <h2 class="section-title" style="font-size:1.4rem">All ${sel.counts.algos} algos</h2>
        <p class="section-intro">Click a row for its eligibility reasons and regime fit. Sortable columns: trades → deploy score.</p>
      </div>
      <div class="controls">
        <input type="search" id="sel-search" placeholder="Search algos…" aria-label="Search algos" />
        <label class="btn ghost" style="cursor:pointer">
          <input type="checkbox" id="sel-fits" style="margin-right:6px">Fits today only
        </label>
      </div>
      <div id="sel-table"></div>
    </div>

    <div class="section" id="sel-heat"></div>
  </div>`;

  paintStrip(t, sel.counts);
  paintDeploy(sel, byId);
  paintCopy(sel, byId);
  paintDrop(sel, byId);
  paintTable(ROWS);
  paintHeat(byId.get(st.sel));

  const onInput = e => { if (e.target.id === 'sel-search') { st.search = e.target.value; paintTable(ROWS); } };
  const onChange = e => { if (e.target.id === 'sel-fits') { st.fitsOnly = e.target.checked; paintTable(ROWS); } };
  const onClick = e => {
    const th = e.target.closest('#sel-table th[data-k]');
    if (th) { const k = th.dataset.k; st.dir = st.sort === k ? -st.dir : -1; st.sort = k; paintTable(ROWS); return; }
    const row = e.target.closest('tr[data-id]');
    if (row) {
      const id = row.dataset.id;
      st.sel = id;
      st.expanded = st.expanded === id ? null : id;
      paintTable(ROWS);
      paintHeat(byId.get(id));
    }
  };
  root.addEventListener('input', onInput);
  root.addEventListener('change', onChange);
  root.addEventListener('click', onClick);
  return () => { root.removeEventListener('input', onInput); root.removeEventListener('change', onChange); root.removeEventListener('click', onClick); };
}

// ---- today's regime strip ----
function paintStrip(t, counts) {
  const trendCls = t.trend === 'bull' ? 'pos' : t.trend === 'bear' ? 'neg' : 'flat';
  const vixChgSign = t.vix_chg_5d > 0 ? '+' : '';
  document.querySelector('#sel-strip').innerHTML = scorecard([
    { label: 'Trend (20d)', value: `<span class="${trendCls}">${TREND_LABEL[t.trend] || t.trend}</span>`, sm: true },
    { label: 'India VIX', value: t.vix.toFixed(2), sm: true, delta: `${t.vix_tercile} tercile · ${vixChgSign}${(t.vix_chg_5d * 100).toFixed(1)}% 5d` },
    { label: 'IV rank', value: t.iv_rank != null ? t.iv_rank.toFixed(1) : '—', sm: true, delta: `${t.iv_tercile} tercile · as of ${fmtDate(t.iv_as_of)}` },
    { label: 'CE–PE skew', value: t.skew != null ? (t.skew * 100).toFixed(2) + '%' : '—', sm: true, delta: `${t.skew_sign} sign` },
    { label: 'DTE', value: DTE_LABEL[t.dte_bucket] || t.dte_bucket, sm: true, delta: `weekly expiry ${fmtDate(t.nifty_weekly_expiry)}` },
  ]);
}

// ---- deploy shortlist ----
function paintDeploy(sel, byId) {
  const ids = sel.shortlist.deploy;
  document.querySelector('#sel-deploy').innerHTML = `
    <div class="section-head" style="margin-bottom:16px">
      <div class="eyebrow">Deploy shortlist</div>
      <h2 class="section-title" style="font-size:1.4rem">Greedy top ${ids.length}, capped at ${sel.rules.deploy.shortlist_max}</h2>
      <p class="section-intro">Picked by score; each pick must clear the deploy gates and stay under ${sel.rules.deploy.max_abs_corr_to_book} correlation against the book and earlier picks.</p>
    </div>
    <div class="grid grid-auto">
      ${ids.map(id => algoCard(byId.get(id), 'deploy')).join('')}
    </div>`;
}

// ---- copy shortlist + risk block ----
function paintCopy(sel, byId) {
  const ids = sel.shortlist.copy;
  const cs = sel.copy_set;
  const inBook = new Set(cs.in_book), needsDeploy = new Set(cs.needs_deploy_first);
  document.querySelector('#sel-copy').innerHTML = `
    <div class="section-head" style="margin-bottom:16px">
      <div class="eyebrow">Copy shortlist</div>
      <h2 class="section-title" style="font-size:1.4rem">${ids.length} algos the copier should track</h2>
      <p class="section-intro">Requires NIFTY (the copier sizes in 65-unit lots), ${sel.rules.copy.min_trades}+ trades, PF ≥ ${sel.rules.copy.min_pf}, Calmar ≥ ${sel.rules.copy.min_calmar}, and today's VIX + IV-rank terciles both non-negative historically.</p>
    </div>
    <div class="grid grid-auto" style="margin-bottom:20px">
      ${ids.map(id => algoCard(byId.get(id), 'copy', {
        chip: inBook.has(id) ? 'In book already' : needsDeploy.has(id) ? 'Needs deploy first' : null,
        chipCls: inBook.has(id) ? 'tag-muted' : 'tag-thin',
      })).join('')}
    </div>
    <div class="card"><div class="card-head"><h3>Risk across the ${ids.length}-algo copy set</h3><span class="sub">replayed against history</span></div>
      <div class="card-pad">
        ${scorecard([
          { label: 'Pooled naked worst day', value: fmtInr(Math.round(cs.pooled_naked_worst_day_rs)), sm: true, cls: 'neg', delta: `kill cap ${fmtInr(-sel.rules.copy.naked_worst_day_max_rs)}` },
          { label: 'Days over kill cap', value: fmtNum(cs.pooled_days_over_kill_cap), sm: true, delta: `of ${fmtNum(cs.pooled_days)} pooled days` },
          { label: 'Skew-gate replay', value: fmtPct(cs.skew_replay.blocked_pct), sm: true, cls: 'neg', delta: `${fmtNum(cs.skew_replay.blocked_by_skew)} of ${fmtNum(cs.skew_replay.entries)} copies blocked` },
          { label: 'Extra margin / copy', value: fmtInr(cs.extra_margin_est_rs_per_concurrent_copy), sm: true, delta: 'estimate, per concurrent copy' },
        ])}
        <p class="muted" style="font-size:.78rem;margin-top:14px">Bias mix: ${Object.entries(cs.bias_mix).map(([k, v]) => `${v} ${escapeHtml(k)}`).join(' · ')}. Naked risk is entry→exit prices only — it doesn't see intra-trade excursion, so the true tail is worse than shown.</p>
      </div>
    </div>`;
}

function algoCard(a, kind, opts = {}) {
  if (!a) return '';
  const d = kind === 'deploy' ? a.deploy : a.copy;
  return `<div class="card"><div class="card-pad" style="padding:var(--s4) var(--s5)">
    <div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px">
      <div style="font-weight:500">${escapeHtml(a.name)}</div>
      <span class="mono pos" style="font-size:.85rem;font-weight:600">${d.score.toFixed(0)}</span>
    </div>
    <div style="margin:6px 0 10px;display:flex;gap:6px;flex-wrap:wrap">${catTag(a.category)}<span class="${biasCls(a.bias)}" style="font-size:.72rem">${escapeHtml(a.bias)}</span>${opts.chip ? `<span class="tag ${opts.chipCls || 'tag-thin'}">${escapeHtml(opts.chip)}</span>` : ''}</div>
    <div class="muted" style="font-size:.76rem">${fmtNum(a.metrics.trades)}t · PF ${a.metrics.pf_inf ? '∞' : a.metrics.pf.toFixed(2)} · Calmar ${a.metrics.calmar.toFixed(2)} · margin ${fmtInr(Math.round(a.metrics.margin_per_lot))}/lot</div>
    <a href="#/algo/${encodeURIComponent(a.id)}" class="btn ghost" style="margin-top:12px;font-size:.76rem;padding:5px 10px">Open deep dive →</a>
  </div></div>`;
}

// ---- drop from book ----
function paintDrop(sel, byId) {
  const ids = sel.shortlist.drop_from_book;
  const host = document.querySelector('#sel-drop');
  if (!ids.length) {
    host.innerHTML = `<div class="section-head" style="margin-bottom:12px"><div class="eyebrow">Drop from book</div>
      <h2 class="section-title" style="font-size:1.4rem">Nothing to drop today</h2></div>`;
    return;
  }
  host.innerHTML = `
    <div class="section-head" style="margin-bottom:16px">
      <div class="eyebrow">Drop from book</div>
      <h2 class="section-title" style="font-size:1.4rem">${ids.length} algo${ids.length > 1 ? 's' : ''} failing to earn its allocation</h2>
      <p class="section-intro">Fails both the PF and Calmar gates, or a Calmar below 0.5, or negative in 2+ non-thin trend buckets.</p>
    </div>
    <div class="grid grid-auto">
      ${ids.map(id => {
        const a = byId.get(id); if (!a) return '';
        return `<div class="card"><div class="card-pad" style="padding:var(--s4) var(--s5)">
          <div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px">
            <div style="font-weight:500">${escapeHtml(a.name)}</div>${catTag(a.category)}
          </div>
          <div class="muted" style="font-size:.78rem;margin-top:8px">${escapeHtml(a.rationale)}</div>
          <div class="muted" style="font-size:.76rem;margin-top:8px">${fmtNum(a.metrics.trades)}t · Calmar ${a.metrics.calmar.toFixed(2)} · margin ${fmtInr(Math.round(a.metrics.margin_per_lot))}/lot</div>
        </div></div>`;
      }).join('')}
    </div>`;
}

// ---- full sortable table ----
function rows(ROWS) {
  let list = ROWS.slice();
  if (st.search) { const q = st.search.toLowerCase(); list = list.filter(r => r.name.toLowerCase().includes(q)); }
  if (st.fitsOnly) list = list.filter(r => r.verdict !== 'unfavourable');
  const k = st.sort;
  list.sort((x, y) => st.dir * ((x[k] ?? -1e9) - (y[k] ?? -1e9)));
  return list;
}

function paintTable(ROWS) {
  const list = rows(ROWS);
  const th = (k, l, cls = 'num') => `<th class="${cls} ${st.sort === k ? 'sorted' + (st.dir === 1 ? ' asc' : '') : ''}" data-k="${k}">${l}</th>`;
  document.querySelector('#sel-table').innerHTML = `
  <div class="table-wrap">
    <table class="data"><thead><tr>
      <th>Algo</th><th>Structure</th>
      ${th('trades', 'Trades')}${th('wr', 'Win %')}${th('pf', 'PF')}${th('calmar', 'Calmar')}
      ${th('margin_per_lot', 'Margin/lot')}${th('corr_to_book', 'Corr→book')}
      <th>Fits today</th>${th('deploy_score', 'Deploy')}${th('copy_score', 'Copy')}
    </tr></thead><tbody>
      ${list.map(a => `<tr data-id="${a.id}" class="clickable"${a.id === st.sel ? ' style="background:var(--surface-2)"' : ''}>
        <td class="name-cell">${escapeHtml(a.name)}${a.in_book ? ' <span class="tag tag-muted">book</span>' : ''}<div class="sub">${catTag(a.category)}</div></td>
        <td><span class="${biasCls(a.bias)}" style="font-size:.76rem">${escapeHtml(a.structure.replace(/_/g, ' '))}</span></td>
        <td class="num">${fmtNum(a.trades)}</td>
        <td class="num">${fmtPct(a.wr)}</td>
        <td class="num">${a.pf === Infinity ? '∞' : a.pf.toFixed(2)}</td>
        <td class="num">${a.calmar.toFixed(2)}</td>
        <td class="num">${fmtInr(Math.round(a.margin_per_lot))}</td>
        <td class="num">${a.corr_to_book.toFixed(2)}</td>
        <td>${verdictTag(a.verdict)}</td>
        <td class="num">${scoreTag(a.deploy_eligible, a.deploy_score)}</td>
        <td class="num">${scoreTag(a.copy_eligible, a.copy_score)}</td>
      </tr>${st.expanded === a.id ? `<tr><td colspan="11" data-label="" style="background:var(--surface-2);padding:16px 18px;text-align:left">
        <div style="text-align:left">
          <div class="muted" style="font-size:.82rem;margin-bottom:10px">${escapeHtml(a.rationale)}</div>
          <div class="two-up">
            <div><div class="eyebrow" style="font-size:.6rem">Deploy reasons</div>${a.deploy_reasons.map(reasonLine).join('')}</div>
            <div><div class="eyebrow" style="font-size:.6rem">Copy reasons</div>${a.copy_reasons.map(reasonLine).join('')}</div>
          </div>
        </div>
      </td></tr>` : ''}`).join('')}
    </tbody></table>
  </div>
  <p class="muted" style="font-size:.76rem;margin-top:10px">${fmtNum(list.length)} of ${fmtNum(ROWS.length)} shown. Click a row for its full eligibility reasons and regime fit below.</p>`;
}

// ---- per-algo regime heatmap ----
async function paintHeat(a) {
  const host = document.querySelector('#sel-heat');
  if (!a) { host.innerHTML = ''; return; }
  host.innerHTML = `<div class="card"><div class="card-head"><h3>Regime fit — ${escapeHtml(a.name)}</h3><span class="sub">avg ₹/trade by bucket, this algo, all history</span></div>
    <div class="card-pad hscroll"><div class="loading" style="padding:0">Loading regime panel…</div></div></div>`;
  const p = await panelFor(a.id);
  const pad = host.querySelector('.card-pad');
  if (!p) { pad.innerHTML = `<div class="note">No regime-panel row for this algo (thin history).</div>`; return; }
  const dims = Object.keys(DIM_BUCKETS);
  const allVals = dims.flatMap(d => DIM_BUCKETS[d].map(b => (p.cells[d] || {})[b]?.avg_rs)).filter(v => v != null);
  const max = Math.max(...allVals.map(Math.abs), 1);
  pad.innerHTML = `
    <table class="data t-wide" style="text-align:center"><tbody>
      ${dims.map(d => {
        const cells = p.cells[d] || {};
        return `<tr><td style="text-align:left;font-weight:500;white-space:nowrap">${DIM_LABEL[d]}</td>
          ${DIM_BUCKETS[d].map(b => {
            const c = cells[b];
            if (!c) return `<td class="muted" style="opacity:.35">·</td>`;
            const bg = c.thin ? 'var(--surface-2)' : heatBg(c.avg_rs, max);
            const op = c.thin ? '0.55' : '1';
            return `<td style="background:${bg};opacity:${op};border-radius:6px" title="${c.thin ? 'thin sample, n<10 — ' : ''}n=${c.n} · WR ${c.wr.toFixed(0)}%">
              <div class="mono" style="font-size:.86rem">${fmtInr(Math.round(c.avg_rs), true)}</div>
              <div class="muted" style="font-size:.6rem">${BUCKET_LABEL[b]} · ${c.n}t</div>
            </td>`;
          }).join('')}
        </tr>`;
      }).join('')}
    </tbody></table>
    <p class="muted" style="font-size:.72rem;margin-top:10px">Muted cells are thin samples (n&lt;10) — direction is indicative, not a signal. Blank = no trades recorded in that bucket.</p>`;
}
