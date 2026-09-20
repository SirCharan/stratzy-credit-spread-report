// components.js — shared UI pieces (drawer, control rail, scorecard, section head).

import { $, escapeHtml } from './util.js';
import * as store from './store.js';

// ---- drawer ----
export function openDrawer(html) {
  $('#drawer').innerHTML = `<button class="btn ghost drawer-close" id="drawer-x" aria-label="Close">✕ Close</button>` + html;
  $('#drawer').classList.add('open');
  $('#drawer').setAttribute('aria-hidden', 'false');
  $('#drawer-scrim').classList.add('open');
  $('#drawer-x').onclick = closeDrawer;
}
export function closeDrawer() {
  $('#drawer').classList.remove('open');
  $('#drawer').setAttribute('aria-hidden', 'true');
  $('#drawer-scrim').classList.remove('open');
}
$('#drawer-scrim')?.addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

// ---- shared control rail (reads/writes the param store; wired by global delegation in app.js) ----
export function controlRail({ category = true, search = true, returns = true, period = true } = {}) {
  const s = store.get();
  const seg = (key, opts) => `<div class="seg" role="group">
    <span class="seg-label">${opts.label}</span>
    ${opts.vals.map(([v, t]) => `<button data-set="${key}" data-val="${v}" class="${s[key] === v ? 'active' : ''}">${t}</button>`).join('')}
  </div>`;
  return `<div class="controls">
    ${period ? seg('period', { label: 'Rank by', vals: [['2026', '2026 YTD'], ['all', 'All-time'], ['1y', 'Stratzy 1Y']] }) : ''}
    ${returns ? seg('returns', { label: 'Returns', vals: [['gross', 'Gross'], ['net', 'Net of fees']] }) : ''}
    ${category ? seg('category', { label: 'Book', vals: [['all', 'All'], ['credit_spread', 'Credit spreads'], ['option_buying', 'Option buying']] }) : ''}
    ${search ? `<input id="ctl-search" type="search" placeholder="Search algos…" value="${escapeHtml(s.search)}" aria-label="Search algos" />` : ''}
  </div>`;
}

// ---- scorecard ----
export function scorecard(tiles) {
  return `<div class="scorecard">${tiles.map(t => `
    <div class="tile"${t.title ? ` title="${escapeHtml(t.title)}"` : ''}>
      <div class="label">${escapeHtml(t.label)}</div>
      <div class="value ${t.sm ? 'sm' : ''} ${t.cls || ''}">${t.value}</div>
      ${t.delta ? `<div class="delta ${t.deltaCls || ''}">${t.delta}</div>` : ''}
    </div>`).join('')}</div>`;
}

export function sectionHead(eyebrow, title, intro) {
  return `<div class="section-head">
    <div class="eyebrow">${escapeHtml(eyebrow)}</div>
    <h1 class="section-title">${title}</h1>
    ${intro ? `<p class="section-intro">${intro}</p>` : ''}
  </div>`;
}

// category tag for a unified algo
export function bookTag(cat) {
  return cat === 'credit_spread'
    ? `<span class="tag tag-cs">Credit spread</span>`
    : `<span class="tag tag-ob">Option buying</span>`;
}
export function styleTag(style, label) {
  if (!style) return '';
  return `<span class="tag tag-${escapeHtml(style)}">${escapeHtml(label || style.replace(/_/g, ' '))}</span>`;
}
