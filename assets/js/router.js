// router.js — tiny hash router with :param support. Routes serve into #app.

const routes = [];
let notFound = () => {};
let current = null;
let cleanup = null;

export function route(pattern, handler) {
  // pattern like '/algo/:id' → regex
  const keys = [];
  const rx = new RegExp('^' + pattern.replace(/:[^/]+/g, m => { keys.push(m.slice(1)); return '([^/]+)'; }) + '$');
  routes.push({ rx, keys, handler, pattern });
}
export function setNotFound(fn) { notFound = fn; }

function parse() {
  const h = location.hash.replace(/^#/, '') || '/';
  return h.split('?')[0];
}
export function query() {
  const q = location.hash.split('?')[1] || '';
  return Object.fromEntries(new URLSearchParams(q));
}
export function go(path) { location.hash = path; }

async function resolve() {
  const path = parse();
  for (const r of routes) {
    const m = path.match(r.rx);
    if (m) {
      const params = {};
      r.keys.forEach((k, i) => params[k] = decodeURIComponent(m[i + 1]));
      if (typeof cleanup === 'function') { try { cleanup(); } catch {} }
      cleanup = null;
      current = r.pattern;
      window.scrollTo(0, 0);
      updateNav(path);
      const ret = await r.handler(params, query());
      if (typeof ret === 'function') cleanup = ret;
      return;
    }
  }
  current = null; updateNav(path); notFound();
}

function updateNav(path) {
  document.querySelectorAll('.topnav a[data-route]').forEach(a => {
    const base = '/' + (path.split('/')[1] || '');
    a.classList.toggle('active', a.dataset.route === base || (base === '/' && a.dataset.route === '/'));
  });
}

export function start() {
  window.addEventListener('hashchange', resolve);
  resolve();
}
export function currentRoute() { return current; }
