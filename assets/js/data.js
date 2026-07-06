// data.js — single cached data layer over the static JSON files.

const cache = new Map();
const inflight = new Map();

// fetch ./<name>.json exactly once
export function load(name) {
  if (cache.has(name)) return Promise.resolve(cache.get(name));
  if (inflight.has(name)) return inflight.get(name);
  const p = fetch(`./${name}.json`)
    .then(r => { if (!r.ok) throw new Error(`${name}.json → ${r.status}`); return r.json(); })
    .then(j => { cache.set(name, j); inflight.delete(name); return j; })
    .catch(e => { inflight.delete(name); console.error(e); throw e; });
  inflight.set(name, p);
  return p;
}
export function loadMany(names) { return Promise.all(names.map(load)); }
export function peek(name) { return cache.get(name); }

// preloaded on boot
export async function boot() {
  const [explore, equity, headlines] = await loadMany(['explore_data', 'equity_curves', 'stratzy_headlines']);
  // index equity curves by id for O(1) lookup
  const eqById = new Map(equity.algos.map(a => [a.id, a]));
  return { explore, equity, headlines, eqById };
}

// equity curve point-array for an algo id, by mode
export function curveFor(equity, id, { x = 'daily', y = 'pts', period = 'all' } = {}) {
  const a = equity.algos.find(z => z.id === id);
  if (!a) return null;
  const root = period === '2026' ? a.curves_2026 : a.curves;
  return root && root[`${x}_${y}`] || null;
}

// the dateline edition string from the freshest generated_at we have
export function edition(explore) {
  return explore.generated_at || '';
}
