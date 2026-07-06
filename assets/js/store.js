// store.js — one shared parameter store; every view subscribes (coordinated cross-filtering).

export const FEE_PTS = 1.5;   // per-trade slippage/fee proxy, points
export const FEE_INR = 100;   // per-trade slippage/fee proxy, ₹ (1 lot)

const KEY = 'stratzy_almanac_params_v1';
const defaults = {
  period: '2026',        // '2026' | 'all' | '1y'  (rank metric + emphasis)
  returns: 'gross',      // 'gross' | 'net'
  category: 'all',       // 'all' | 'credit_spread' | 'option_buying'
  search: '',
};

let state = { ...defaults };
try { Object.assign(state, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch {}
state.search = ''; // never persist a stale search

const subs = new Set();
export function get() { return state; }
export function set(patch) {
  state = { ...state, ...patch };
  const { search, ...persist } = state;
  try { localStorage.setItem(KEY, JSON.stringify(persist)); } catch {}
  subs.forEach(fn => fn(state));
}
export function subscribe(fn) { subs.add(fn); return () => subs.delete(fn); }

// helpers reading current period for a unified explore_data algo
export function metricKey() {
  return get().period === 'all' ? 'all_time_pts' : get().period === '1y' ? 'one_year_pnl_pct' : 'ytd_2026_pts';
}
export function periodLabel() {
  return get().period === 'all' ? 'All-time' : get().period === '1y' ? 'Stratzy 1Y' : '2026 YTD';
}
// net adjustment for a points/inr value given trade count
export function netPts(gross, trades) { return get().returns === 'net' ? gross - trades * FEE_PTS : gross; }
export function netInr(gross, trades) { return get().returns === 'net' ? gross - trades * FEE_INR : gross; }
