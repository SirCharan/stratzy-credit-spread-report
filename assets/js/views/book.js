// book.js — 1Y ₹5L-per-name backtest of the live+parked Stratzy book.
import { load } from '../data.js';
import * as store from '../store.js';
import { sectionHead, scorecard, controlRail } from '../components.js';
import { fmtInr, fmtLakh, fmtPct, fmtDate, fmtNum, pnlClass, escapeHtml, sparkSVG, downloadCsv } from '../util.js';
import { ddBandPlugin, underwaterRanges } from '../chartdd.js';
import { parseCsv, pathStats, tradeStats } from '../book-stats.js';

const GRID = '#2b261e', TICK = '#8A8070';
let charts = [];
function kill() { charts.forEach(c => { try { c.destroy(); } catch {} }); charts = []; }

export async function render(root) {
  const [d, tradeRows] = await Promise.all([
    load('book_backtest'),
    fetch('./book_trades.csv')
      .then(r => r.ok ? r.text() : '')
      .then(t => parseCsv(t))
      .catch(() => []),
  ]);
  root.innerHTML = `<div class="fade-in">
    ${sectionHead('The book', '₹5L in every name, past year',
      `If each of the <b>${d.n_algos}</b> algos on the account (10 live + 7 parked) had <b>₹5L</b> from <b>${fmtDate(d.window.start)}</b> to <b>${fmtDate(d.window.end)}</b>.
      Lots = min(4, floor(₹5L / Stratzy min capital)). Cash until that name’s first live fill — no invented history.
      P&amp;L is recomputed from fills, not Stratzy’s 1Y card.`)}
    ${controlRail({ period: false, category: false, search: false, returns: true })}
    <div id="book-score"></div>
    <div class="chart-frame" style="margin-top:18px"><div class="chart-canvas-wrap" style="height:420px"><canvas id="book-eq"></canvas></div></div>
    <div id="book-monthly" style="margin-top:26px"></div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin:12px 0">
      <a class="btn ghost" href="./book_trades.csv" download="almanac-5L-book-trades.csv">Download all trades CSV</a>
      <button class="btn ghost" id="book-csv">Export CSV</button>
    </div>
    <div id="book-table"></div>
    <p class="muted" style="margin-top:16px;font-size:.78rem;max-width:72ch">
      Deployed <span class="mono">${fmtInr(d.deployed_inr)}</span> of
      <span class="mono">${fmtInr(d.notional_inr)}</span> notional
      (<span class="mono">${fmtInr(d.idle_inr)}</span> leftover idle).
      Net deducts modelled Dhan charges per leg on entry and exit (brokerage, STT, exchange, SEBI, stamp, GST; calibrated to Dhan’s statement). Lots capped at 4.
      Stratzy’s 2% subscription is <b>not</b> deducted. ⚠ = fewer than 20 fills in the window.
      Trades CSV = every closed fill in the window, one row each, gross and net.
      Path stats use Nifty trading days, daily P&amp;L / deployed, rf = 0, 252d.
      Calmar = CAGR / |max DD ÷ deployed|. VaR = 5th percentile of 1-day ₹ P&amp;L.
      Trade stats pool the CSV fills (win rate, profit factor, avg win/loss, expectancy, payoff, max consecutive losses in time order).
      MoM % = that month’s P&amp;L / deployed.
    </p>
  </div>`;

  const paint = () => {
    paintScore(d, tradeRows);
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

function fmtRatio(n, dp = 2) {
  if (n == null || !isFinite(n)) return n === Infinity ? '∞' : '—';
  return n.toFixed(dp);
}

function paintScore(d, tradeRows) {
  const host = document.querySelector('#book-score'); if (!host) return;
  const net = store.get().returns === 'net';
  const tot = net ? d.combined.total_net : d.combined.total_gross;
  const dd = net ? d.combined.max_dd_net : d.combined.max_dd_gross;
  const pct = d.deployed_inr ? 100 * tot / d.deployed_inr : 0;
  const days = d.combined.win_days + d.combined.loss_days;
  const path = pathStats({
    daily: net ? d.combined.daily_net : d.combined.daily_gross,
    nifty: d.nifty,
    deployed: d.deployed_inr,
    total: tot,
    maxDd: dd,
    start: d.window.start,
    end: d.window.end,
  });
  const tr = tradeStats(tradeRows, net ? 'pnl_net' : 'pnl_gross');
  host.innerHTML = scorecard([
    { label: net ? '1Y net' : '1Y gross', value: fmtInr(Math.round(tot), true), sm: true, cls: pnlClass(tot) },
    { label: 'On deployed', value: fmtPct(pct, 1, true), sm: true, cls: pnlClass(pct) },
    { label: 'Max drawdown', value: fmtInr(Math.round(dd)), sm: true, cls: 'neg' },
    { label: 'Win days', value: `${d.combined.win_days}/${days}`, sm: true, delta: fmtPct(days ? 100 * d.combined.win_days / days : 0, 0) },
    { label: 'Deployed', value: fmtLakh(d.deployed_inr), sm: true, delta: `${d.n_enabled} live · ${d.n_parked} parked` },
  ]) + `<div class="score-group">
    <div class="eyebrow">Path · daily / deployed</div>
    ${scorecard([
      { label: 'CAGR', value: fmtPct(path.cagr != null ? 100 * path.cagr : null, 1, true), sm: true, cls: pnlClass(path.cagr), delta: '1Y window', title: 'CAGR of (1 + total / deployed) over the window' },
      { label: 'Calmar', value: fmtRatio(path.calmar), sm: true, cls: pnlClass(path.calmar), delta: 'CAGR ÷ |DD|', title: 'CAGR divided by max drawdown as a fraction of deployed' },
      { label: 'Sharpe', value: fmtRatio(path.sharpe), sm: true, delta: `rf 0 · ${fmtNum(path.n)}d`, title: 'Mean daily return / stdev × √252, Nifty trading days, rf = 0' },
      { label: 'VaR 95% · 1d', value: fmtInr(Math.round(path.var95)), sm: true, cls: pnlClass(path.var95), delta: '5th pctile', title: '5th percentile of 1-day book P&L in ₹' },
    ])}
  </div>
  <div class="score-group">
    <div class="eyebrow">Trades · ${fmtNum(tr.n)} fills</div>
    ${scorecard([
      { label: 'Win rate', value: fmtPct(tr.winRate, 1), sm: true, delta: `${fmtNum(tr.wins)}W / ${fmtNum(tr.losses)}L` },
      { label: 'Profit factor', value: fmtRatio(tr.profitFactor), sm: true, cls: pnlClass((tr.profitFactor || 0) - 1), delta: 'W ÷ |L|' },
      { label: 'Avg win', value: fmtInr(Math.round(tr.avgWin)), sm: true, cls: 'pos', delta: `${fmtNum(tr.wins)} fills` },
      { label: 'Avg loss', value: fmtInr(Math.round(tr.avgLoss)), sm: true, cls: 'neg', delta: `${fmtNum(tr.losses)} fills` },
      { label: 'Expectancy', value: fmtInr(Math.round(tr.expectancy), true), sm: true, cls: pnlClass(tr.expectancy), delta: '₹ / fill' },
      { label: 'Payoff', value: fmtRatio(tr.payoff), sm: true, delta: 'W ÷ |L|' },
      { label: 'Max consec L', value: fmtNum(tr.maxConsecLoss), sm: true, cls: 'neg', delta: 'time order', title: 'Longest losing streak across all 17 names, CSV time order' },
    ])}
  </div>`;
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
  const deployed = d.deployed_inr || 0;
  const vals = keys.map(k => net ? d.monthly[k].net : d.monthly[k].gross);
  const max = Math.max(...vals.map(v => Math.abs(v)), 1);
  const startM = (d.window.start || '').slice(0, 7);
  const endM = (d.window.end || '').slice(0, 7);
  host.innerHTML = `<div class="eyebrow" style="margin-bottom:12px">Month on month · % of deployed</div>
    <div class="mom">${keys.map((k, i) => {
      const v = vals[i];
      const pct = deployed ? 100 * v / deployed : 0;
      const h = Math.abs(v) / max * 100;
      const partial = k === startM || k === endM;
      const trades = (d.monthly[k] || {}).trades || 0;
      const tone = pct > 0 ? 'up' : pct < 0 ? 'down' : '';
      return `<div class="mom-col" title="${k}: ${fmtPct(pct, 1, true)} · ${fmtInr(Math.round(v), true)} · ${fmtNum(trades)} fills${partial ? ' · partial' : ''}">
        <span class="mom-pct ${tone}">${fmtPct(pct, 1, true)}</span>
        <div class="mom-track"><div class="mom-bar" style="height:${h}%;background:${pct >= 0 ? 'var(--gain)' : 'var(--loss)'}"></div></div>
        <span class="mom-lab">${k.slice(2)}${partial ? '*' : ''}</span>
      </div>`;
    }).join('')}</div>
    <p class="muted" style="font-size:.7rem;margin-top:8px">Month P&amp;L / deployed. * partial month.</p>`;
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
