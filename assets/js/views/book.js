// book.js — 1Y ₹5L-per-name backtest of the live+parked Stratzy book.
import { load } from '../data.js';
import * as store from '../store.js';
import { sectionHead, scorecard, controlRail } from '../components.js';
import { fmtInr, fmtLakh, fmtPct, fmtDate, fmtNum, pnlClass, escapeHtml, sparkSVG, downloadCsv } from '../util.js';
import { ddBandPlugin, underwaterRanges } from '../chartdd.js';

const GRID = '#2b261e', TICK = '#8A8070';
let charts = [];
function kill() { charts.forEach(c => { try { c.destroy(); } catch {} }); charts = []; }

export async function render(root) {
  const d = await load('book_backtest');
  root.innerHTML = `<div class="fade-in">
    ${sectionHead('The book', '₹5L in every name, past year',
      `If each of the <b>${d.n_algos}</b> algos on the account (10 live + 7 parked) had <b>₹5L</b> from <b>${fmtDate(d.window.start)}</b> to <b>${fmtDate(d.window.end)}</b>.
      Lots = floor(₹5L / Stratzy min capital). Cash until that name’s first live fill — no invented history.
      P&amp;L is recomputed from fills, not Stratzy’s 1Y card.`)}
    ${controlRail({ period: false, category: false, search: false, returns: true })}
    <div id="book-score"></div>
    <div class="chart-frame" style="margin-top:18px"><div class="chart-canvas-wrap" style="height:420px"><canvas id="book-eq"></canvas></div></div>
    <div id="book-monthly" style="margin-top:26px"></div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin:12px 0">
      <button class="btn ghost" id="book-csv">Export CSV</button>
    </div>
    <div id="book-table"></div>
    <p class="muted" style="margin-top:16px;font-size:.78rem;max-width:72ch">
      Deployed <span class="mono">${fmtInr(d.deployed_inr)}</span> of
      <span class="mono">${fmtInr(d.notional_inr)}</span> notional
      (<span class="mono">${fmtInr(d.idle_inr)}</span> leftover idle).
      Net haircut is ₹${d.fee_inr_per_lot_trade} × lots per fill (Almanac proxy, not Dhan’s schedule).
      Stratzy’s 2% subscription is <b>not</b> deducted. ⚠ = fewer than 20 fills in the window.
    </p>
  </div>`;

  const paint = () => {
    paintScore(d);
    paintChart(d);
    paintMonthly(d);
    paintTable(d);
  };
  paint();
  const unsub = store.subscribe(paint);
  const onClick = e => {
    if (e.target.id === 'book-csv') {
      const net = store.get().returns === 'net';
      downloadCsv('almanac-5L-book.csv', d.algos.map(a => ({
        name: a.name, mode: a.mode, lots: a.lots, deployed: a.deployed_inr,
        first_fill: a.first_fill, trades: a.trades,
        pnl: net ? a.total_net : a.total_gross,
        pct_on_deployed: a.pct_on_deployed, max_dd: net ? a.max_dd_net : a.max_dd_gross,
      })));
    }
  };
  root.addEventListener('click', onClick);
  return () => { unsub(); kill(); root.removeEventListener('click', onClick); };
}

function series(d) {
  return store.get().returns === 'net' ? d.combined.daily_net : d.combined.daily_gross;
}
function algoSeries(a) {
  return store.get().returns === 'net' ? a.daily_net : a.daily_gross;
}

function paintScore(d) {
  const host = document.querySelector('#book-score'); if (!host) return;
  const net = store.get().returns === 'net';
  const tot = net ? d.combined.total_net : d.combined.total_gross;
  const dd = net ? d.combined.max_dd_net : d.combined.max_dd_gross;
  const pct = d.deployed_inr ? 100 * tot / d.deployed_inr : 0;
  const days = d.combined.win_days + d.combined.loss_days;
  host.innerHTML = scorecard([
    { label: net ? '1Y net' : '1Y gross', value: fmtInr(Math.round(tot), true), sm: true, cls: pnlClass(tot) },
    { label: 'On deployed', value: fmtPct(pct, 1, true), sm: true, cls: pnlClass(pct) },
    { label: 'Max drawdown', value: fmtInr(Math.round(dd)), sm: true, cls: 'neg' },
    { label: 'Win days', value: `${d.combined.win_days}/${days}`, sm: true, delta: fmtPct(days ? 100 * d.combined.win_days / days : 0, 0) },
    { label: 'Deployed', value: fmtLakh(d.deployed_inr), sm: true, delta: `${d.n_enabled} live · ${d.n_parked} parked` },
  ]);
}

function paintChart(d) {
  kill();
  const el = document.getElementById('book-eq'); if (!el || !window.Chart) return;
  const s = series(d);
  const nifty = d.nifty || [];
  const ranges = underwaterRanges(s);
  charts.push(new Chart(el, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Book',
          data: s.map(p => ({ x: p.x, y: p.y })),
          borderColor: '#E8A33D',
          backgroundColor: 'rgba(232,163,61,0.10)',
          borderWidth: 2.2, fill: true, pointRadius: 0, tension: 0.06, yAxisID: 'y',
        },
        nifty.length ? {
          label: 'Nifty (100 = start)',
          data: nifty.map(p => ({ x: p.x, y: p.y })),
          borderColor: '#6FB4F2', borderWidth: 1.4, pointRadius: 0, tension: 0.06,
          fill: false, yAxisID: 'y1',
        } : null,
      ].filter(Boolean),
    },
    plugins: [ddBandPlugin(() => ranges, () => true)],
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { type: 'time', time: { tooltipFormat: 'dd MMM yyyy' }, ticks: { color: TICK, maxTicksLimit: 10 }, grid: { color: GRID } },
        y: { ticks: { color: TICK, callback: v => '₹' + (v / 100000).toFixed(1) + 'L' }, grid: { color: GRID }, title: { display: true, text: 'Book ₹', color: TICK, font: { size: 11 } } },
        y1: { position: 'right', ticks: { color: '#6FB4F2', callback: v => v.toFixed(0) }, grid: { drawOnChartArea: false }, title: { display: true, text: 'Nifty idx', color: '#6FB4F2', font: { size: 11 } } },
      },
      plugins: {
        legend: { display: true, labels: { color: TICK, boxWidth: 12 } },
        tooltip: { callbacks: { label: it => it.dataset.yAxisID === 'y1'
          ? `Nifty ${it.parsed.y.toFixed(1)}`
          : '₹' + Math.round(it.parsed.y).toLocaleString('en-IN') } },
      },
    },
  }));
}

function paintMonthly(d) {
  const host = document.querySelector('#book-monthly'); if (!host) return;
  const net = store.get().returns === 'net';
  const keys = Object.keys(d.monthly || {}).sort();
  if (!keys.length) { host.innerHTML = ''; return; }
  const vals = keys.map(k => net ? d.monthly[k].net : d.monthly[k].gross);
  const max = Math.max(...vals.map(v => Math.abs(v)), 1);
  host.innerHTML = `<div class="eyebrow" style="margin-bottom:12px">Combined by month · ₹</div>
    <div style="display:flex;gap:6px;align-items:flex-end;height:130px">${keys.map((k, i) => {
      const v = vals[i]; const h = Math.abs(v) / max * 100;
      return `<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px" title="${k}: ${fmtInr(Math.round(v), true)}">
        <div style="width:70%;height:${h}%;min-height:2px;background:${v>=0?'#46C68C':'#F2615C'};border-radius:3px 3px 0 0"></div>
        <span class="muted" style="font-size:.6rem">${k.slice(2)}</span></div>`;
    }).join('')}</div>`;
}

function paintTable(d) {
  const host = document.querySelector('#book-table'); if (!host) return;
  const net = store.get().returns === 'net';
  host.innerHTML = `<div class="table-wrap"><table class="data">
    <thead><tr>
      <th>Algo</th><th>Mode</th><th class="num">Lots</th><th>First fill</th>
      <th class="num">Trades</th><th class="num">1Y ₹</th><th class="num">On capital</th>
      <th class="num">Max DD</th><th>Path</th>
    </tr></thead>
    <tbody>${d.algos.map(a => {
      const tot = net ? a.total_net : a.total_gross;
      const dd = net ? a.max_dd_net : a.max_dd_gross;
      const pct = a.deployed_inr ? 100 * tot / a.deployed_inr : 0;
      const ys = algoSeries(a).filter((_, i) => i % 3 === 0).map(p => p.y);
      const spark = ys.length > 1 ? sparkSVG(ys, { w: 96, h: 26, color: tot >= 0 ? '#46C68C' : '#F2615C' }) : '';
      const mode = (a.mode || '').toUpperCase();
      const tag = a.enabled ? (a.mode === 'manual' ? 'tag-ob' : 'tag-cs') : 'tag-muted';
      return `<tr class="${a.enabled ? '' : 'muted'}" data-id="${escapeHtml(a.id)}">
        <td><a href="#/algo/${encodeURIComponent(a.id)}">${escapeHtml(a.name)}</a>
          ${a.thin ? ' <span title="thin sample">&nbsp;⚠</span>' : ''}
          <div class="muted" style="font-size:.7rem">${fmtLakh(a.deployed_inr)} deployed</div></td>
        <td><span class="tag ${tag}">${escapeHtml(mode)}</span></td>
        <td class="num">${fmtNum(a.lots)}</td>
        <td class="muted">${a.first_fill ? fmtDate(a.first_fill) : '—'}</td>
        <td class="num">${fmtNum(a.trades)}</td>
        <td class="num ${pnlClass(tot)}">${fmtInr(Math.round(tot), true)}</td>
        <td class="num ${pnlClass(pct)}">${fmtPct(pct, 1, true)}</td>
        <td class="num neg">${fmtInr(Math.round(dd))}</td>
        <td>${spark}</td>
      </tr>`;
    }).join('')}</tbody>
  </table></div>`;
}
