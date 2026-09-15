// app.js — bootstrap: data, masthead, global controls, command palette, routes.

import { boot, load } from './data.js';
import * as store from './store.js';
import * as router from './router.js';
import * as cmdk from './cmdk.js';
import { $, fmtDate, debounce, reflowTables } from './util.js';

const app = () => $('#app');

async function main() {
  let DB;
  try { DB = await boot(); }
  catch (e) {
    app().innerHTML = `<div class="note">Couldn't load the data files. Serve this folder over HTTP (e.g. <span class="chip">python3 serve.py</span>) and reload.<br><br>${e.message}</div>`;
    return;
  }

  // dateline / footer
  const ed = fmtDate(DB.explore.generated_at);
  const s = DB.explore.summary || {};
  let uniN = s.total, csN = s.credit_spread_count, obN = s.option_buying_count;
  try {
    const uni = await load('universe');
    uniN = uni.total ?? uniN;
  } catch {}
  $('#dateline').innerHTML =
    `<span>Fills · <b>${ed}</b></span><span class="dot">·</span>` +
    `<span><b>${uniN ?? '—'}</b> catalog</span><span class="dot">·</span>` +
    `<span><b>${csN ?? '—'}</b> CS deep</span><span class="dot">·</span>` +
    `<span><b>${obN ?? '—'}</b> OB deep</span>`;
  $('#foot-right').textContent = `Recomputed per-trade · net premium points & ₹ per 1 lot · fills ${ed}`;

  // ---- global store-control delegation (cross-filtering) ----
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-set]');
    if (b) store.set({ [b.dataset.set]: b.dataset.val });
  });
  const onSearch = debounce(v => store.set({ search: v }), 160);
  document.addEventListener('input', e => { if (e.target.id === 'ctl-search') onSearch(e.target.value); });

  // ---- command palette ----
  cmdk.init(buildCommands(DB));

  // ---- mobile: reflow data tables into label:value cards after every render.
  // Observe childList only (not attributes) so the label-stamping doesn't re-trigger us. ----
  const doReflow = debounce(() => reflowTables(app()), 60);
  new MutationObserver(doReflow).observe(app(), { childList: true, subtree: true });

  // ---- routes (views lazy-loaded) ----
  const mount = (mod) => async (params, query) => {
    app().innerHTML = `<div class="loading">Composing…</div>`;
    const m = await import(mod);
    return m.render(app(), params, query);
  };
  const carry = q => q.tab ? '&tab=' + encodeURIComponent(q.tab) : '';
  router.route('/',           mount('./views/today.js'));
  router.route('/algos',      mount('./views/algos.js'));
  router.route('/universe',   () => router.go('#/algos?sub=universe'));
  router.route('/compare',    mount('./views/compare.js'));
  router.route('/studio',     mount('./views/studio.js'));
  router.route('/charts',     (p, q) => router.go('#/studio?sub=charts' + carry(q)));
  router.route('/portfolio',  (p, q) => router.go('#/studio?sub=portfolio' + carry(q)));
  router.route('/playbook',   mount('./views/playbook.js'));
  router.route('/guide',      () => router.go('#/playbook?sub=guide'));
  router.route('/regime',     () => router.go('#/playbook?sub=regime'));
  router.route('/movers',     () => router.go('#/'));
  router.route('/book',       mount('./views/book.js'));
  router.route('/algo/:id',   mount('./views/algo.js'));
  router.setNotFound(() => { app().innerHTML = `<div class="note">No such page. <a href="#/">Back to Algos →</a></div>`; });
  router.start();
}

function buildCommands(DB) {
  const navs = [
    ['Today — live book', '/'], ['Rankings', '/algos?sub=rankings'], ['Universe', '/algos?sub=universe'], ['Compare & families', '/compare'],
    ['Charts — equity & overlay', '/studio?sub=charts'], ['What-if combiner', '/studio?sub=charts&tab=whatif'],
    ['Portfolio builder', '/studio?sub=portfolio&tab=builder'], ['Correlation matrix', '/studio?sub=portfolio&tab=correlation'],
    ['Portfolio doctor', '/studio?sub=portfolio&tab=doctor'],
    ['Field guide', '/playbook?sub=guide'], ['Regime — when strategies make money', '/playbook?sub=regime'],
    ['Today — live book + movers', '/'],
    ['5L book backtest — past year', '/book'],
  ];
  const settings = [
    ['Rank by 2026 YTD', () => store.set({ period: '2026' })],
    ['Rank by all-time points', () => store.set({ period: 'all' })],
    ['Rank by Stratzy 1Y %', () => store.set({ period: '1y' })],
    ['Show gross returns', () => store.set({ returns: 'gross' })],
    ['Show net of fees', () => store.set({ returns: 'net' })],
    ['Book: all', () => store.set({ category: 'all' })],
    ['Book: credit spreads', () => store.set({ category: 'credit_spread' })],
    ['Book: option buying', () => store.set({ category: 'option_buying' })],
  ];
  return (q) => {
    const out = [];
    const ql = q.toLowerCase();
    navs.filter(([l]) => l.toLowerCase().includes(ql)).forEach(([l, p]) =>
      out.push({ group: 'Go to', label: l, hint: p, run: () => router.go('#' + p) }));
    settings.filter(([l]) => l.toLowerCase().includes(ql)).forEach(([l, run]) =>
      out.push({ group: 'Set', label: l, hint: 'param', run }));
    if (ql.length >= 1) {
      DB.explore.algos
        .filter(a => (a.name + a.short_name).toLowerCase().includes(ql))
        .slice(0, 8)
        .forEach(a => out.push({
          group: 'Algos', label: a.name,
          hint: a.category === 'credit_spread' ? 'CS' : 'OB',
          run: () => router.go('#/algo/' + a.id),
        }));
    }
    return out;
  };
}

main();
