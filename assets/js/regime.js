// regime.js — Nifty market-regime classification (realized, fully local) + per-strategy attribution.
// Direction: trailing 20-trading-day Nifty close return (>=+2% bull, <=-2% bear, else sideways).
// Volatility: trailing 20-day realized vol (annualised), tercile-split (low/normal/high).
// Each trade is tagged by the regime of its EXIT date (nearest prior trading day) — exact for
// ~overnight credit spreads, an approximation for multi-day option-buying holds.

export const DIR_WINDOW = 20, DIR_BULL = 2.0, DIR_BEAR = -2.0;
export const VOL_WINDOW = 20;
const ANN = Math.sqrt(252);
export const DIRS = ['bull', 'sideways', 'bear'];
export const VOLS = ['low', 'normal', 'high'];

function stdev(arr) {
  const n = arr.length; if (n < 2) return 0;
  const m = arr.reduce((s, v) => s + v, 0) / n;
  return Math.sqrt(arr.reduce((s, v) => s + (v - m) ** 2, 0) / n);
}
function quantile(sorted, q) {
  if (!sorted.length) return 0;
  const pos = (sorted.length - 1) * q, base = Math.floor(pos), rest = pos - base;
  return sorted[base + 1] !== undefined ? sorted[base] + rest * (sorted[base + 1] - sorted[base]) : sorted[base];
}

// nifty_daily: { "YYYY-MM-DD": {open, close, day_return_pct} }
// Returns { map: Map<dateStr,{dir,vol,trail20,rvol}>, dates: string[], volCutoffs:{low,high} }
export function buildNiftyRegime(niftyDaily) {
  const dates = Object.keys(niftyDaily).sort();
  const close = dates.map(d => niftyDaily[d].close);
  // own close-to-close returns (don't trust day_return_pct units)
  const ret = close.map((c, i) => i ? c / close[i - 1] - 1 : 0);
  const dir = dates.map((d, i) => {
    if (i < DIR_WINDOW) return 'sideways';
    const chg = (close[i] / close[i - DIR_WINDOW] - 1) * 100;
    return chg >= DIR_BULL ? 'bull' : chg <= DIR_BEAR ? 'bear' : 'sideways';
  });
  const rvol = dates.map((d, i) => i < VOL_WINDOW ? null : stdev(ret.slice(i - VOL_WINDOW + 1, i + 1)) * ANN);
  const valid = rvol.filter(v => v != null).sort((a, b) => a - b);
  const lo = quantile(valid, 1 / 3), hi = quantile(valid, 2 / 3);
  const map = new Map();
  dates.forEach((d, i) => {
    const rv = rvol[i];
    const vol = rv == null ? 'normal' : rv <= lo ? 'low' : rv >= hi ? 'high' : 'normal';
    map.set(d, { dir: dir[i], vol, trail20: i >= DIR_WINDOW ? (close[i] / close[i - DIR_WINDOW] - 1) * 100 : null, rvol: rv });
  });
  return { map, dates, volCutoffs: { low: lo, high: hi } };
}

// regime for a date, falling back to the nearest prior trading day
export function nearestRegime(regime, dateStr) {
  if (regime.map.has(dateStr)) return regime.map.get(dateStr);
  const dates = regime.dates;
  let lo = 0, hi = dates.length - 1, ans = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (dates[mid] <= dateStr) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
  return ans >= 0 ? regime.map.get(dates[ans]) : null;
}

const blank = () => ({ trades: 0, total_pts: 0, wins: 0, avg_pts: 0, win_rate: 0 });
function push(b, pnl) { b.trades++; b.total_pts += pnl; if (pnl > 0) b.wins++; }
function finalize(b) { b.avg_pts = b.trades ? b.total_pts / b.trades : 0; b.win_rate = b.trades ? 100 * b.wins / b.trades : 0; return b; }

// overall trade stats from a trade array ([{x,day_pnl}]) — win rate, avg win/loss, profit factor.
export function tradeStats(tradeArr) {
  const arr = tradeArr || [];
  let winSum = 0, winN = 0, lossSum = 0, lossN = 0, total = 0;
  for (const t of arr) {
    const pnl = t.day_pnl ?? 0; total += pnl;
    if (pnl > 0) { winSum += pnl; winN++; } else { lossSum += pnl; lossN++; }
  }
  const n = arr.length;
  return {
    trades: n, wins: winN, losses: lossN,
    winRate: n ? 100 * winN / n : 0,
    avgWin: winN ? winSum / winN : 0,
    avgLoss: lossN ? lossSum / lossN : 0,
    profitFactor: lossSum !== 0 ? Math.abs(winSum / lossSum) : (winSum > 0 ? Infinity : 0),
    totalPts: total,
  };
}

// full attribution of a strategy's trades across direction, volatility and the 3×3 cross.
export function attributeStrategy(tradeArr, regime) {
  const dir = { bull: blank(), sideways: blank(), bear: blank() };
  const vol = { low: blank(), normal: blank(), high: blank() };
  const cross = {};
  for (const d of DIRS) for (const v of VOLS) cross[`${d}_${v}`] = blank();
  for (const t of (tradeArr || [])) {
    const pnl = t.day_pnl ?? 0;
    const r = nearestRegime(regime, t.x);
    if (!r) continue;
    push(dir[r.dir], pnl); push(vol[r.vol], pnl); push(cross[`${r.dir}_${r.vol}`], pnl);
  }
  for (const k in dir) finalize(dir[k]);
  for (const k in vol) finalize(vol[k]);
  for (const k in cross) finalize(cross[k]);
  return { overall: tradeStats(tradeArr), dir, vol, cross };
}
