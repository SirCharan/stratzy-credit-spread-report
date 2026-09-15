// subnav.js — thin wrapper that hosts existing views as sub-tabs (clubs tabs without rewriting them).
// Each child view's render(root, params, query) returns a teardown; we reuse it on switch/exit.

export function subTabs(root, { label, items, query }) {
  // items: [{ id, label, mod }]   query carries ?sub (which child) and any child params like ?tab
  const initial = (query && query.sub) || items[0].id;
  root.innerHTML = `<div class="seg" id="subnav" style="margin-bottom:18px"><span class="seg-label">${label}</span>
    ${items.map(it => `<button data-sub="${it.id}">${escapeName(it.label)}</button>`).join('')}</div>
    <div id="subnav-body"></div>`;
  const seg = root.querySelector('#subnav'), body = root.querySelector('#subnav-body');
  let sub = null, token = 0;
  const mount = async id => {
    const it = items.find(x => x.id === id) || items[0];
    [...seg.querySelectorAll('button')].forEach(b => b.classList.toggle('active', b.dataset.sub === it.id));
    if (sub) { try { sub(); } catch {} sub = null; }
    const mine = ++token;
    body.innerHTML = `<div class="loading">Composing…</div>`;
    const m = await import(it.mod);
    if (mine !== token) return;               // a newer switch superseded this mount
    sub = await m.render(body, {}, { ...query, sub: it.id });
  };
  const onClick = e => {
    const b = e.target.closest('button[data-sub]');
    if (!b) return;
    const id = b.dataset.sub;
    const h = location.hash.split('?')[0] || '#/algos';
    const qs = new URLSearchParams(location.hash.split('?')[1] || '');
    qs.set('sub', id);
    history.replaceState(null, '', h + '?' + qs.toString());
    mount(id);
  };
  seg.addEventListener('click', onClick);
  mount(initial);
  return () => { seg.removeEventListener('click', onClick); if (sub) { try { sub(); } catch {} } };
}

function escapeName(s) { return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }
