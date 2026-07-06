// guide.js — Field Guide view: all 38 option-buying algos with methodology, filters, regime strips, sparklines.

import { load } from '../data.js';
import { sectionHead } from '../components.js';
import { fmtPts, fmtPct, fmtNum, pnlClass, escapeHtml, dualSparkSVG } from '../util.js';

// Local filter state — NOT the global store (per spec)
let filters = { search: '', family: '', trend: '', market_fit: '', active: '' };

export async function render(root, params, query) {
  root.innerHTML = `<div class="loading">Loading field guide…</div>`;

  let data;
  try {
    data = await load('option_buying_strategy_guide');
  } catch (err) {
    root.innerHTML = `<div class="note" style="margin-top:24px"><b>Could not load field guide data.</b> ${escapeHtml(String(err))}</div>`;
    return () => {};
  }

  const { methodology, families, algos, pairwise_highlights } = data;

  // Render static skeleton; card grid re-renders on filter changes
  root.innerHTML = `<div class="fade-in">
    ${sectionHead('The field guide', 'How each option-buying algo behaves',
      `Regime and trend labels are inferred from trade fills and Nifty price data — not copied from Stratzy marketing copy.`)}

    ${renderMethodology(methodology)}

    <div style="margin-bottom:32px">
      <div class="eyebrow" style="margin-bottom:12px">Strategy families</div>
      <div class="grid grid-auto">${families.map(familyCard).join('')}</div>
    </div>

    <div class="controls" id="guide-filters">
      <input id="gf-search" type="search" placeholder="Search algos…" value="${escapeHtml(filters.search)}" aria-label="Search algos" />
      <select id="gf-family" aria-label="Filter by family">
        <option value="">All families</option>
        ${families.map(f => `<option value="${escapeHtml(f.id)}" ${filters.family === f.id ? 'selected' : ''}>${escapeHtml(f.title)}</option>`).join('')}
      </select>
      <select id="gf-trend" aria-label="Filter by trend">
        <option value="">All trends</option>
        <option value="trend_following" ${filters.trend === 'trend_following' ? 'selected' : ''}>Trend-following</option>
        <option value="mean_reverting" ${filters.trend === 'mean_reverting' ? 'selected' : ''}>Mean-reverting</option>
        <option value="hybrid" ${filters.trend === 'hybrid' ? 'selected' : ''}>Hybrid</option>
      </select>
      <select id="gf-fit" aria-label="Filter by market fit">
        <option value="">All market fits</option>
        <option value="bull_market" ${filters.market_fit === 'bull_market' ? 'selected' : ''}>Bull market</option>
        <option value="bear_market" ${filters.market_fit === 'bear_market' ? 'selected' : ''}>Bear market</option>
        <option value="sideways_market" ${filters.market_fit === 'sideways_market' ? 'selected' : ''}>Sideways market</option>
        <option value="bull_day_alpha" ${filters.market_fit === 'bull_day_alpha' ? 'selected' : ''}>Bull-day alpha</option>
        <option value="bear_day_alpha" ${filters.market_fit === 'bear_day_alpha' ? 'selected' : ''}>Bear-day alpha</option>
        <option value="all_weather" ${filters.market_fit === 'all_weather' ? 'selected' : ''}>All weather</option>
      </select>
      <select id="gf-active" aria-label="Filter by active/inactive">
        <option value="">Active + inactive</option>
        <option value="active" ${filters.active === 'active' ? 'selected' : ''}>Active only</option>
        <option value="inactive" ${filters.active === 'inactive' ? 'selected' : ''}>Inactive only</option>
      </select>
    </div>

    <div id="guide-cards" class="grid grid-auto" style="margin-bottom:48px"></div>

    ${renderPairwise(pairwise_highlights)}
  </div>`;

  // initial card paint
  repaintCards(root, algos);

  // delegated listener
  const onClick = (e) => {
    const tog = e.target.closest('[data-spark-id]');
    if (tog) { toggleSpark(tog, algos); return; }
  };

  const onInput = (e) => {
    const t = e.target;
    if (t.id === 'gf-search') { filters.search = t.value; repaintCards(root, algos); }
    else if (t.id === 'gf-family') { filters.family = t.value; repaintCards(root, algos); }
    else if (t.id === 'gf-trend') { filters.trend = t.value; repaintCards(root, algos); }
    else if (t.id === 'gf-fit') { filters.market_fit = t.value; repaintCards(root, algos); }
    else if (t.id === 'gf-active') { filters.active = t.value; repaintCards(root, algos); }
  };

  root.addEventListener('click', onClick);
  root.addEventListener('input', onInput);
  root.addEventListener('change', onInput);

  return () => {
    root.removeEventListener('click', onClick);
    root.removeEventListener('input', onInput);
    root.removeEventListener('change', onInput);
  };
}

// ---------- methodology note ----------
function renderMethodology(m) {
  if (!m) return '';
  return `<div class="note" style="margin-bottom:28px">
    <b>How these labels are inferred</b>
    <ul style="margin-top:8px;padding-left:20px;line-height:1.9;font-size:.85rem">
      <li><b>Strategy type:</b> ${escapeHtml(m.strategy_type ?? '—')}</li>
      <li><b>Moneyness:</b> ${escapeHtml(m.moneyness ?? '—')}</li>
      <li><b>Regime:</b> ${escapeHtml(m.regime ?? '—')}</li>
      <li><b>Trend:</b> ${escapeHtml(m.trend ?? '—')}</li>
    </ul>
    <p style="margin-top:10px;font-size:.8rem;color:var(--ink-3)">${escapeHtml(m.not_stratzy_copy ?? '')}</p>
  </div>`;
}

// ---------- family card ----------
function familyCard(f) {
  return `<div class="card card-pad" style="padding:18px 20px">
    <div style="display:flex;align-items:baseline;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px">
      <div style="font-family:var(--serif);font-size:1.05rem;font-weight:500;letter-spacing:-.01em">${escapeHtml(f.title)}</div>
      <span class="chip">${escapeHtml(String(f.member_count))} algos</span>
    </div>
    <div class="muted" style="font-size:.82rem">${escapeHtml(f.subtitle ?? '')}</div>
  </div>`;
}

// ---------- filter + repaint ----------
function applyFilters(algos) {
  let list = algos.slice();
  const q = filters.search.trim().toLowerCase();
  if (q) list = list.filter(a => (a.name + ' ' + (a.short_name ?? '')).toLowerCase().includes(q));
  if (filters.family) list = list.filter(a => (a.family_id ?? '') === filters.family);
  if (filters.trend) list = list.filter(a => (a.trend_label ?? '') === filters.trend);
  if (filters.market_fit) list = list.filter(a => (a.market_fit ?? '') === filters.market_fit);
  if (filters.active === 'active') list = list.filter(a => !a.inactive_2026);
  if (filters.active === 'inactive') list = list.filter(a => !!a.inactive_2026);
  return list;
}

function repaintCards(root, algos) {
  const host = root.querySelector('#guide-cards');
  if (!host) return;
  const list = applyFilters(algos);
  if (!list.length) {
    host.innerHTML = `<p class="muted" style="grid-column:1/-1;padding:32px 0;text-align:center">No algos match these filters.</p>`;
    return;
  }
  host.innerHTML = list.map(algoCard).join('');
}

// ---------- algo card ----------
function algoCard(a) {
  const ytdCls = pnlClass(a.ytd_2026_pts);
  const inactiveBadge = a.inactive_2026
    ? `<span class="tag tag-thin" style="margin-left:4px">Inactive 2026</span>`
    : '';

  // CE/PE bar
  const ce = a.ce_pct ?? 0;
  const pe = a.pe_pct ?? 0;
  const ceBar = ce > 0
    ? `<div style="display:flex;align-items:center;gap:8px;margin:8px 0 4px">
        <div class="wlbar" style="width:100%;flex:1">
          <i class="w" style="width:${ce.toFixed(1)}%;background:var(--cs)"></i>
          <i class="l" style="width:${pe.toFixed(1)}%;background:var(--loss)"></i>
        </div>
        <span style="font-family:var(--mono);font-size:.68rem;color:var(--ink-3);white-space:nowrap">CE ${fmtPct(ce, 0)} / PE ${fmtPct(pe, 0)}</span>
      </div>`
    : '';

  // Regime strip
  const reg = a.metrics?.regime ?? {};
  const regimes = ['bull', 'sideways', 'bear'];
  const regLabels = { bull: 'Bull', sideways: 'Sdwy', bear: 'Bear' };
  const regStrip = `<div style="display:flex;gap:4px;margin:8px 0 4px;flex-wrap:wrap">
    ${regimes.map(r => {
      const d = reg[r];
      const pts = d?.avg_pts ?? 0;
      const tr = d?.trades ?? 0;
      const cls = pnlClass(pts);
      return `<div style="flex:1;min-width:64px;background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;text-align:center">
        <div style="font-family:var(--mono);font-size:.6rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)">${regLabels[r]}</div>
        <div class="${cls}" style="font-family:var(--mono);font-size:.78rem;font-variant-numeric:tabular-nums;margin-top:2px">${fmtPts(pts)}</div>
        <div style="font-family:var(--mono);font-size:.6rem;color:var(--ink-4)">${fmtNum(tr)} tr</div>
      </div>`;
    }).join('')}
  </div>`;

  // Bullets
  const bullets = (a.bullets ?? []).slice(0, 4);
  const bulletList = bullets.length
    ? `<ul style="margin:8px 0 4px;padding-left:16px;font-size:.8rem;color:var(--ink-2);line-height:1.7">
        ${bullets.map(b => `<li>${escapeHtml(b)}</li>`).join('')}
      </ul>`
    : '';

  // Trend label display
  const trendDisplay = (a.trend_label ?? '').replace(/_/g, ' ');
  const fitDisplay = (a.market_fit ?? '').replace(/_/g, ' ');

  // Metrics line
  const moneyness = a.metrics?.dominant_moneyness ?? '—';
  const moneypct = a.metrics?.moneyness_pct ?? {};
  const mVal = moneypct[moneyness];
  const metricsLine = `<div style="font-family:var(--mono);font-size:.72rem;color:var(--ink-3);margin:6px 0 2px;display:flex;gap:12px;flex-wrap:wrap">
    <span>${escapeHtml(moneyness.replace(/_/g, ' '))}${mVal != null ? ` ${fmtPct(mVal, 0)}` : ''}</span>
    <span>${fmtNum(a.trades_per_month, 1)} tr/mo</span>
    <span>${escapeHtml(a.avg_frequency ?? '—')}</span>
  </div>`;

  const sparkId = escapeHtml(a.id);

  return `<div class="card" style="display:flex;flex-direction:column">
    <div class="card-head" style="padding:14px 16px 12px">
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">
          <span style="font-family:var(--serif);font-size:1.05rem;font-weight:500;letter-spacing:-.01em">${escapeHtml(a.short_name ?? a.name)}</span>
          <span class="${ytdCls}" style="font-family:var(--mono);font-size:.78rem;font-variant-numeric:tabular-nums">${fmtPts(a.ytd_2026_pts)}</span>
          ${inactiveBadge}
        </div>
        <div style="margin-top:5px;display:flex;gap:5px;flex-wrap:wrap;align-items:center">
          <span class="tag tag-ob" style="font-size:.6rem">${escapeHtml(a.family_title ?? '')}</span>
          ${trendDisplay ? `<span class="tag tag-muted" style="font-size:.6rem">${escapeHtml(trendDisplay)}</span>` : ''}
          ${fitDisplay ? `<span class="tag tag-muted" style="font-size:.6rem">${escapeHtml(fitDisplay)}</span>` : ''}
        </div>
      </div>
    </div>
    <div style="padding:0 16px 4px;flex:1">
      ${ceBar}
      ${metricsLine}
      ${regStrip}
      ${bulletList}
    </div>
    <div style="padding:8px 16px 14px;border-top:1px solid var(--border);margin-top:auto">
      <button class="btn ghost" data-spark-id="${sparkId}" style="font-size:.76rem;padding:5px 10px;width:100%;justify-content:center;margin-bottom:8px">Show vs-Nifty curve</button>
      <div id="spark-${sparkId}" style="display:none;text-align:center;margin-bottom:8px"></div>
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
        <span class="muted" style="font-family:var(--mono);font-size:.7rem">All-time: <span class="${pnlClass(a.all_time_pts)}">${fmtPts(a.all_time_pts)}</span> pts</span>
        <a href="#/algo/${escapeHtml(a.id)}" style="font-size:.78rem">Open deep dive →</a>
      </div>
    </div>
  </div>`;
}

// ---------- lazy sparkline toggle ----------
function toggleSpark(btn, algos) {
  const id = btn.dataset.sparkId;
  const container = btn.parentElement?.querySelector(`#spark-${id}`);
  if (!container) return;

  const isOpen = container.style.display !== 'none';
  if (isOpen) {
    container.style.display = 'none';
    btn.textContent = 'Show vs-Nifty curve';
    return;
  }

  // Build SVG only on first expand
  if (!container.dataset.built) {
    const algo = algos.find(a => a.id === id);
    const ov = algo?.nifty_overlay;
    if (ov && ov.cum_pnl?.length > 1 && ov.nifty_indexed?.length > 1) {
      container.innerHTML = dualSparkSVG(ov.cum_pnl, ov.nifty_indexed, { w: 268, h: 56, ca: '#E8A33D', cb: '#6FB4F2' })
        + `<div style="display:flex;gap:16px;justify-content:center;margin-top:5px;font-family:var(--mono);font-size:.62rem;color:var(--ink-3)">
            <span><span style="display:inline-block;width:10px;height:2px;background:#E8A33D;vertical-align:middle;margin-right:3px"></span>Algo PnL</span>
            <span><span style="display:inline-block;width:10px;height:2px;background:#6FB4F2;vertical-align:middle;margin-right:3px"></span>Nifty (indexed)</span>
          </div>`;
    } else {
      container.innerHTML = `<span class="muted" style="font-size:.75rem">Insufficient data for curve</span>`;
    }
    container.dataset.built = '1';
  }

  container.style.display = 'block';
  btn.textContent = 'Hide curve';
}

// ---------- pairwise section ----------
function renderPairwise(pairs) {
  if (!pairs?.length) return '';
  return `<div style="margin-top:8px">
    <div class="eyebrow" style="margin-bottom:14px">How to pick between two</div>
    <div class="grid grid-auto">
      ${pairs.map(p => `
        <div class="card card-pad" style="padding:16px 18px">
          <div style="font-family:var(--sans);font-weight:500;font-size:.88rem;margin-bottom:8px">${escapeHtml(p.headline ?? '')}</div>
          <div style="font-family:var(--mono);font-size:.66rem;color:var(--gold);margin-bottom:8px;letter-spacing:.04em">
            ${escapeHtml(p.from ?? '')} <span style="color:var(--ink-4)">vs</span> ${escapeHtml(p.to ?? '')}
          </div>
          <ul style="padding-left:16px;font-size:.8rem;color:var(--ink-2);line-height:1.7">
            ${(p.bullets ?? []).map(b => `<li>${escapeHtml(b)}</li>`).join('')}
          </ul>
        </div>`).join('')}
    </div>
  </div>`;
}
