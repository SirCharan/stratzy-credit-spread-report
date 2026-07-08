// universe.js — the full 148-algo Stratzy universe + screener (headline metrics).

import { load } from '../data.js';
import { sectionHead, scorecard, openDrawer } from '../components.js';
import { fmtPct, fmtNum, fmtInr, fmtLakh, fmtPts, pnlClass, escapeHtml, fmtDate } from '../util.js';

const CAT_COLORS = {
  'Credit Spread': 'tag-cs', 'Option Buying': 'tag-ob',
};
function catTag(c) {
  return `<span class="tag ${CAT_COLORS[c] || 'tag-muted'}">${escapeHtml(c || '—')}</span>`;
}

let st = { cat: 'all', sort: 'ret_1y', dir: -1, search: '', deepOnly: false, style: 'all', bias: 'all' };
let INS = null; // algo_insights.json {algos:{id:profile}} — powers the AI style/bias filters

export async function render(root) {
  const [uni, insights] = await Promise.all([
    load('universe'),
    load('algo_insights').catch(() => null),
  ]);
  INS = insights && insights.algos ? insights.algos : null;

  root.innerHTML = `<div class="fade-in">
    ${sectionHead('The universe', 'Every algo Stratzy publishes',
      `All <b>${uni.total}</b> live algos across ${Object.keys(uni.categories).length} categories — screened on the metrics Stratzy buries: Sharpe, risk:reward, max drawdown, recovery time, popularity. <b>${uni.deep_count}</b> carry our recomputed per-trade data (★) — click those for the full deep dive.`)}
    <div id="u-score"></div>
    <div class="controls" style="margin:18px 0">
      <select id="u-cat"><option value="all">All categories (${uni.total})</option>
        ${Object.entries(uni.categories).sort((a,b)=>b[1]-a[1]).map(([c,n])=>`<option value="${escapeHtml(c)}">${escapeHtml(c)} (${n})</option>`).join('')}</select>
      <select id="u-sort">
        ${[['ret_1y','1Y return'],['ret_6m','6M return'],['ret_3m','3M return'],['sharpe','Sharpe'],['rr','Risk:reward'],['win_ratio','Win %'],['max_dd','Max drawdown'],['score','Algo score'],['deploy_count','Popularity'],['recovery_days','Recovery days']].map(([v,l])=>`<option value="${v}">Sort: ${l}</option>`).join('')}
      </select>
      <input type="search" id="u-search" placeholder="Search algos…" />
      <label class="btn ghost" style="cursor:pointer"><input type="checkbox" id="u-deep" style="margin-right:6px">★ deep-data only</label>
      ${INS ? `<select id="u-style"><option value="all">Any style</option>
        <option value="premium">Premium-selling / mean-revert</option>
        <option value="momentum">Trend / momentum</option>
        <option value="neutral">Neutral / range</option></select>
      <select id="u-bias"><option value="all">Any bias</option>
        <option value="put">Put-heavy</option><option value="call">Call-heavy</option>
        <option value="balanced">Balanced</option><option value="both">Both-sided</option></select>` : ''}
    </div>
    <div id="u-table"></div>
    <p class="muted" style="margin-top:14px;font-size:.78rem">Returns are Stratzy's headline trailing figures (return on capital), not our recomputed points. ★ = recomputed per-trade data available.</p>
  </div>`;

  const draw = () => { paintScore(uni); paintTable(uni); };
  draw();

  const onInput = e => { if (e.target.id === 'u-search') { st.search = e.target.value; paintTable(uni); } };
  const onChange = e => {
    if (e.target.id === 'u-cat') { st.cat = e.target.value; draw(); }
    else if (e.target.id === 'u-sort') { st.sort = e.target.value; st.dir = e.target.value === 'max_dd' ? 1 : -1; paintTable(uni); }
    else if (e.target.id === 'u-deep') { st.deepOnly = e.target.checked; draw(); }
    else if (e.target.id === 'u-style') { st.style = e.target.value; draw(); }
    else if (e.target.id === 'u-bias') { st.bias = e.target.value; draw(); }
  };
  const onClick = e => {
    const th = e.target.closest('th[data-k]');
    if (th) { const k = th.dataset.k; st.dir = st.sort === k ? -st.dir : (k === 'max_dd' ? 1 : -1); st.sort = k; paintTable(uni); return; }
    const tr = e.target.closest('tr[data-id]');
    if (tr) openAlgo(tr.dataset.id, uni);
  };
  root.addEventListener('input', onInput);
  root.addEventListener('change', onChange);
  root.addEventListener('click', onClick);
  return () => { root.removeEventListener('input', onInput); root.removeEventListener('change', onChange); root.removeEventListener('click', onClick); };
}

function rows(uni) {
  let list = uni.algos.slice();
  if (st.cat !== 'all') list = list.filter(a => a.category === st.cat);
  if (st.deepOnly) list = list.filter(a => a.deep);
  if (st.search) { const q = st.search.toLowerCase(); list = list.filter(a => (a.name || '').toLowerCase().includes(q)); }
  // AI-profile filters (only algos with a profile qualify when a filter is active)
  if (INS && st.style !== 'all') {
    const want = { premium: 'premium', momentum: 'momentum', neutral: 'neutral' }[st.style];
    list = list.filter(a => { const p = INS[a.id]; return p && (p.style || '').toLowerCase().includes(want); });
  }
  if (INS && st.bias !== 'all') {
    const want = { put: 'put-heavy', call: 'call-heavy', balanced: 'balanced', both: 'both' }[st.bias];
    list = list.filter(a => { const p = INS[a.id]; return p && (p.bias || '').toLowerCase().includes(want); });
  }
  const k = st.sort;
  list.sort((x, y) => st.dir * (((x[k] ?? -1e9)) - ((y[k] ?? -1e9))));
  return list;
}

function paintScore(uni) {
  const list = rows(uni);
  const withSharpe = list.filter(a => a.sharpe != null);
  const bestSharpe = withSharpe.sort((a, b) => b.sharpe - a.sharpe)[0];
  const best1y = list.filter(a => a.ret_1y != null).sort((a, b) => b.ret_1y - a.ret_1y)[0];
  const host = document.querySelector('#u-score');
  host.innerHTML = scorecard([
    { label: 'In view', value: fmtNum(list.length), sm: true, delta: st.cat === 'all' ? 'all categories' : st.cat },
    { label: 'Best 1Y', value: best1y ? fmtPct(best1y.ret_1y) : '—', sm: true, cls: best1y ? pnlClass(best1y.ret_1y) : '', delta: best1y ? escapeHtml(best1y.name.slice(0, 22)) : '' },
    { label: 'Best Sharpe', value: bestSharpe ? bestSharpe.sharpe.toFixed(2) : '—', sm: true, delta: bestSharpe ? escapeHtml(bestSharpe.name.slice(0, 22)) : '' },
    { label: 'Deep-data', value: fmtNum(list.filter(a => a.deep).length), sm: true, delta: 'recomputed ★' },
  ]);
}

function paintTable(uni) {
  const list = rows(uni);
  const th = (k, l, cls = 'num') => `<th class="${cls} ${st.sort === k ? 'sorted' + (st.dir === 1 ? ' asc' : '') : ''}" data-k="${k}">${l}</th>`;
  document.querySelector('#u-table').innerHTML = `
  <div class="table-wrap">
    <table class="data"><thead><tr>
      <th>Algo</th><th>Category</th><th>Risk</th>
      ${th('ret_1y', '1Y %')}${th('ret_6m', '6M %')}${th('ret_3m', '3M %')}
      ${th('win_ratio', 'Win %')}${th('rr', 'R:R')}${th('sharpe', 'Sharpe')}${th('max_dd', 'Max DD')}
      ${th('deploy_count', 'Users')}${th('score', 'Score')}
    </tr></thead><tbody>
      ${list.map(a => `<tr data-id="${a.id}" class="clickable">
        <td class="name-cell">${a.deep ? '<span style="color:var(--gold)">★</span> ' : ''}${escapeHtml(a.name)}${a.in_testing ? ' <span class="tag tag-thin">testing</span>' : ''}<div class="sub">${escapeHtml(a.underlying || a.house || '')}</div></td>
        <td>${catTag(a.category)}</td>
        <td><span class="muted" style="font-size:.74rem">${escapeHtml(a.risk || '—')}</span></td>
        <td class="num ${pnlClass(a.ret_1y)}">${fmtPct(a.ret_1y)}</td>
        <td class="num ${pnlClass(a.ret_6m)}">${fmtPct(a.ret_6m)}</td>
        <td class="num ${pnlClass(a.ret_3m)}">${fmtPct(a.ret_3m)}</td>
        <td class="num">${fmtPct(a.win_ratio)}</td>
        <td class="num">${a.rr != null ? a.rr.toFixed(2) : '—'}</td>
        <td class="num">${a.sharpe != null ? a.sharpe.toFixed(2) : '—'}</td>
        <td class="num neg">${fmtPct(a.max_dd)}</td>
        <td class="num muted">${fmtNum(a.deploy_count)}</td>
        <td class="num">${a.score != null ? a.score.toFixed(0) : '—'}</td>
      </tr>`).join('')}
    </tbody></table>
  </div>`;
}

function openAlgo(id, uni) {
  const a = uni.algos.find(z => z.id === id); if (!a) return;
  const kv = (k, v) => `<tr><td class="muted">${k}</td><td class="num" style="text-align:right">${v}</td></tr>`;
  openDrawer(`
    <div class="drawer-head">
      <div class="eyebrow" style="margin-bottom:8px">${escapeHtml(a.category || '')} · ${escapeHtml(a.underlying || '')} · ${escapeHtml(a.risk || '')} risk</div>
      <h3 style="font-family:var(--serif);font-size:1.5rem;letter-spacing:-.01em">${a.deep ? '★ ' : ''}${escapeHtml(a.name)}</h3>
      <div class="muted" style="font-size:.8rem;margin-top:6px">${escapeHtml(a.house || '')} · live ${fmtDate(a.live_since)} · ${fmtNum(a.deploy_count)} users</div>
    </div>
    <div class="drawer-body">
      ${scorecard([
        { label: '1Y', value: fmtPct(a.ret_1y), sm: true, cls: pnlClass(a.ret_1y) },
        { label: '6M', value: fmtPct(a.ret_6m), sm: true, cls: pnlClass(a.ret_6m) },
        { label: 'Sharpe', value: a.sharpe != null ? a.sharpe.toFixed(2) : '—', sm: true },
      ])}
      <div class="divider"></div>
      <table class="data" style="font-size:.8rem"><tbody>
        ${kv('3M / 1M / 7D', `${fmtPct(a.ret_3m)} / ${fmtPct(a.ret_1m)} / ${fmtPct(a.ret_7d)}`)}
        ${kv('Win ratio', fmtPct(a.win_ratio))}
        ${kv('Risk : reward', a.rr != null ? a.rr.toFixed(2) : '—')}
        ${kv('Sharpe (live / backtest)', `${a.sharpe ?? '—'} / ${a.sharpe_bt ?? '—'}`)}
        ${kv('Max drawdown', fmtPct(a.max_dd))}
        ${kv('CAGR', fmtPct(a.cagr))}
        ${kv('Avg recovery', a.recovery_days != null ? fmtNum(a.recovery_days) + ' days' : '—')}
        ${kv('Algo score', a.score != null ? a.score.toFixed(0) : '—')}
        ${kv('Frequency', escapeHtml(a.frequency || '—'))}
        ${kv('Min capital', a.min_capital ? fmtInr(a.min_capital) : '—')}
        ${a.deep ? kv('Recomputed all-time pts', fmtPts(a.all_time_pts)) : ''}
        ${a.deep ? kv('Recomputed 2026 pts', fmtPts(a.ytd_2026_pts)) : ''}
      </tbody></table>
      ${a.deep ? `<div style="margin-top:18px"><a class="btn primary" href="#/algo/${a.id}">Open full deep dive →</a></div>`
        : `<p class="note" style="margin-top:18px">Headline metrics only — per-trade recompute not packaged for this algo.</p>`}
    </div>`);
}
