// book-stats.js — combined-book path + trade metrics for #/book.
// Path: daily P&L / deployed, rf=0, 252d, nifty trading calendar.
// Trades: pooled fills from book_trades.csv (5L lots).

const SQRT252 = Math.sqrt(252);

function mean(xs) {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
}
function stdev(xs) {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return Math.sqrt(xs.reduce((s, x) => s + (x - m) * (x - m), 0) / (xs.length - 1));
}
function yearsBetween(start, end) {
  const a = Date.parse(start + 'T00:00:00');
  const b = Date.parse(end + 'T00:00:00');
  if (!isFinite(a) || !isFinite(b) || b <= a) return 0;
  return (b - a) / (365.25 * 86400000);
}

export function tradingPnls(daily, nifty) {
  const by = Object.create(null);
  for (const p of daily || []) by[p.x] = Number(p.day_pnl) || 0;
  if (nifty && nifty.length) return nifty.map(p => by[p.x] ?? 0);
  return (daily || []).filter(p => {
    const w = new Date(p.x + 'T00:00:00').getDay();
    return w !== 0 && w !== 6;
  }).map(p => Number(p.day_pnl) || 0);
}

export function pathStats({ daily, nifty, deployed, total, maxDd, start, end }) {
  const empty = { n: 0, sharpe: null, cagr: null, calmar: null, var95: null };
  if (!deployed) return empty;
  const pnls = tradingPnls(daily, nifty);
  const n = pnls.length;
  if (!n) return empty;
  const rets = pnls.map(x => x / deployed);
  const sd = stdev(rets);
  const sharpe = sd > 0 ? (mean(rets) / sd) * SQRT252 : null;
  const years = yearsBetween(start, end);
  const r = total / deployed;
  const cagr = years > 0 && r > -1 ? Math.pow(1 + r, 1 / years) - 1 : null;
  const ddFrac = Math.abs(maxDd || 0) / deployed;
  const calmar = cagr != null && ddFrac > 0 ? cagr / ddFrac : null;
  const sorted = pnls.slice().sort((a, b) => a - b);
  const var95 = sorted[Math.max(0, Math.floor(0.05 * n))];
  return { n, sharpe, cagr, calmar, var95 };
}

export function tradeStats(rows, key) {
  const empty = {
    n: 0, wins: 0, losses: 0, winRate: null, avgWin: null, avgLoss: null,
    profitFactor: null, expectancy: null, payoff: null, maxConsecLoss: 0,
  };
  if (!rows || !rows.length) return empty;
  const pnls = rows.map(r => Number(r[key])).filter(x => Number.isFinite(x));
  const n = pnls.length;
  if (!n) return empty;
  const wins = pnls.filter(x => x > 0);
  const losses = pnls.filter(x => x < 0);
  const sw = wins.reduce((a, b) => a + b, 0);
  const sl = losses.reduce((a, b) => a + b, 0);
  let streak = 0, maxConsecLoss = 0;
  for (const x of pnls) {
    if (x < 0) { streak += 1; if (streak > maxConsecLoss) maxConsecLoss = streak; }
    else streak = 0;
  }
  return {
    n,
    wins: wins.length,
    losses: losses.length,
    winRate: 100 * wins.length / n,
    avgWin: wins.length ? sw / wins.length : null,
    avgLoss: losses.length ? sl / losses.length : null,
    profitFactor: sl < 0 ? sw / Math.abs(sl) : (sw > 0 ? Infinity : null),
    expectancy: mean(pnls),
    payoff: wins.length && losses.length ? (sw / wins.length) / Math.abs(sl / losses.length) : null,
    maxConsecLoss,
  };
}

export function parseCsv(text) {
  if (!text) return [];
  const lines = text.replace(/^\uFEFF/, '').trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  const headers = splitCsvLine(lines[0]);
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    if (!lines[i]) continue;
    const cells = splitCsvLine(lines[i]);
    const o = {};
    for (let j = 0; j < headers.length; j++) o[headers[j]] = cells[j] ?? '';
    rows.push(o);
  }
  return rows;
}

function splitCsvLine(line) {
  const out = [];
  let cur = '', q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (c === '"') q = false;
      else cur += c;
    } else if (c === '"') q = true;
    else if (c === ',') { out.push(cur); cur = ''; }
    else cur += c;
  }
  out.push(cur);
  return out;
}
