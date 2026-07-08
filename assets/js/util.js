// util.js — formatters, DOM helpers, sparklines. No deps.

// --- number formatting (Indian conventions) ---
export function indianGroup(n) {
  const neg = n < 0; let s = Math.round(Math.abs(n)).toString();
  let last3 = s.slice(-3), rest = s.slice(0, -3);
  if (rest) last3 = ',' + last3;
  rest = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',');
  return (neg ? '-' : '') + rest + last3;
}
export function fmtInr(n, sign = false) {
  if (n == null || isNaN(n)) return '—';
  const s = sign && n > 0 ? '+' : '';
  return s + '₹' + indianGroup(n);
}
export function fmtLakh(n) {
  if (n == null || isNaN(n)) return '—';
  const a = Math.abs(n), sgn = n < 0 ? '-' : '';
  if (a >= 1e7) return sgn + '₹' + (a / 1e7).toFixed(2) + 'Cr';
  if (a >= 1e5) return sgn + '₹' + (a / 1e5).toFixed(2) + 'L';
  if (a >= 1e3) return sgn + '₹' + (a / 1e3).toFixed(1) + 'k';
  return sgn + '₹' + Math.round(a);
}
export function fmtPts(n, sign = true) {
  if (n == null || isNaN(n)) return '—';
  const s = sign && n > 0 ? '+' : '';
  return s + n.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}
export function fmtPct(n, dp = 1, sign = false) {
  if (n == null || isNaN(n)) return '—';
  const s = sign && n > 0 ? '+' : '';
  return s + n.toFixed(dp) + '%';
}
export function fmtNum(n, dp = 0) {
  if (n == null || isNaN(n)) return '—';
  return n.toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
export function fmtDate(s) {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

// --- semantic classes ---
export function pnlClass(n) { return n > 0 ? 'pos' : n < 0 ? 'neg' : 'flat'; }
// signed span ready for innerHTML (▲/▼ via .pos/.neg ::before)
export function pnl(n, fmt = fmtPts) {
  const c = pnlClass(n);
  return `<span class="${c}">${fmt(n).replace(/^[+-]?/, m => n < 0 ? '' : '')}</span>`;
}

// --- DOM ---
export function $(sel, root = document) { return root.querySelector(sel); }
export function $$(sel, root = document) { return [...root.querySelectorAll(sel)]; }
export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
export function debounce(fn, ms = 180) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// --- mobile: stamp each <td> with its column header so CSS can reflow tables
// into stacked label:value cards on narrow screens. Idempotent; skips .t-wide
// tables (kept as horizontal-scroll) and any table already stamped. ---
export function reflowTables(root = document) {
  root.querySelectorAll('table.data:not(.t-wide)').forEach(tbl => {
    if (tbl.dataset.reflowed === '1') return;
    const heads = [...tbl.querySelectorAll('thead th')].map(th => th.textContent.trim());
    if (!heads.length) return;
    tbl.querySelectorAll('tbody tr').forEach(tr => {
      [...tr.children].forEach((td, i) => {
        if (td.dataset.label == null) td.dataset.label = heads[i] ?? '';
      });
    });
    tbl.classList.add('t-card');   // opt this table into the mobile card-reflow CSS
    tbl.dataset.reflowed = '1';
  });
}

// --- inline sparkline SVG from array of numbers or {x,y} ---
export function sparkSVG(series, opts = {}) {
  const { w = 88, h = 26, color = '#E8A33D', fill = true, baseline = true } = opts;
  const ys = series.map(p => typeof p === 'number' ? p : p.y);
  if (ys.length < 2) return `<svg width="${w}" height="${h}"></svg>`;
  const min = Math.min(...ys, 0), max = Math.max(...ys, 0);
  const span = (max - min) || 1;
  const px = i => (i / (ys.length - 1)) * (w - 2) + 1;
  const py = v => h - 1 - ((v - min) / span) * (h - 2);
  const line = ys.map((v, i) => `${i ? 'L' : 'M'}${px(i).toFixed(1)} ${py(v).toFixed(1)}`).join(' ');
  const zeroY = py(0).toFixed(1);
  const area = fill ? `<path d="${line} L${px(ys.length - 1).toFixed(1)} ${zeroY} L${px(0).toFixed(1)} ${zeroY} Z" fill="${color}" opacity="0.10"/>` : '';
  const base = baseline ? `<line x1="1" y1="${zeroY}" x2="${w - 1}" y2="${zeroY}" stroke="rgba(244,239,230,0.12)" stroke-width="0.7"/>` : '';
  const up = ys[ys.length - 1] >= ys[0];
  const stroke = opts.color || (up ? '#46C68C' : '#F2615C');
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${base}${area}<path d="${line}" fill="none" stroke="${stroke}" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

// dual-series sparkline (pnl vs benchmark), shared y-range
export function dualSparkSVG(a, b, opts = {}) {
  const { w = 300, h = 56, ca = '#E8A33D', cb = '#6FB4F2' } = opts;
  const ya = a.map(p => p.y), yb = b.map(p => p.y);
  const all = [...ya, ...yb]; if (all.length < 2) return `<svg width="${w}" height="${h}"></svg>`;
  const min = Math.min(...all), max = Math.max(...all), span = (max - min) || 1;
  const path = arr => {
    const px = i => (i / (arr.length - 1)) * (w - 2) + 1;
    const py = v => h - 2 - ((v - min) / span) * (h - 4);
    return arr.map((p, i) => `${i ? 'L' : 'M'}${px(i).toFixed(1)} ${py(p.y).toFixed(1)}`).join(' ');
  };
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <path d="${path(b)}" fill="none" stroke="${cb}" stroke-width="1.2" opacity="0.7"/>
    <path d="${path(a)}" fill="none" stroke="${ca}" stroke-width="1.6"/></svg>`;
}

// --- calendar heatmap cell class from pts/status ---
export function heatCell(status, pts, t1 = 20, t2 = 50) {
  if (!status || status === 'none' || status === 'idle') return '';
  const a = Math.abs(pts || 0);
  const lvl = a < t1 ? 1 : a < t2 ? 2 : a < t2 * 2.2 ? 3 : 4;
  return (status === 'win' ? 'w' : status === 'loss' ? 'l' : '') + lvl;
}

// running max drawdown over a cumulative series of numbers
export function maxDrawdown(cum) {
  let peak = -Infinity, dd = 0;
  for (const v of cum) { if (v > peak) peak = v; dd = Math.min(dd, v - peak); }
  return dd; // <= 0
}
