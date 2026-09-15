// today.js — home desk: live book first, then movers boards.
import { load } from '../data.js';
import { sectionHead, scorecard } from '../components.js';
import { fmtInr, fmtLakh, fmtPct, fmtDate, pnlClass, escapeHtml } from '../util.js';
import { render as renderMovers } from './movers.js';

export async function render(root, params, query) {
  const [book, movers] = await Promise.all([
    load('book_live').catch(() => null),
    load('movers/latest').catch(() => null),
  ]);

  const wrap = document.createElement('div');
  wrap.className = 'fade-in';
  root.innerHTML = '';
  root.appendChild(wrap);

  const edMovers = movers && movers.generated_at;
  const edBook = book && book.generated_at;
  const stale = isStale(edMovers) || isStale(edBook);

  wrap.innerHTML = `
    ${stale ? `<div class="stale-banner" role="status">Numbers last moved ${escapeHtml(fmtDate(edMovers || edBook))}. Fills refresh when a DHAN session is live.</div>` : ''}
    ${sectionHead('Today', 'Your live book',
      `Enabled Stratzy deployments as of <b>${fmtDate(edBook)}</b>. Movers board below is Stratzy headline % (not recomputed points).`)}
    <div id="today-book"></div>
    <div id="today-movers" style="margin-top:36px"></div>
  `;

  paintBook(wrap.querySelector('#today-book'), book);
  const moversRoot = wrap.querySelector('#today-movers');
  const teardown = await renderMovers(moversRoot, params, query);
  return () => { if (typeof teardown === 'function') teardown(); };
}

function isStale(iso) {
  if (!iso) return true;
  const d = new Date(iso);
  if (isNaN(d)) return true;
  const age = Date.now() - d.getTime();
  return age > 2 * 24 * 3600 * 1000;
}

function paintBook(el, book) {
  if (!book || !book.holdings) {
    el.innerHTML = `<div class="note">No live book snapshot. Re-run fetch_live_fills.py.</div>`;
    return;
  }
  const hs = book.holdings;
  const allocated = hs.reduce((s, h) => s + (h.allocated || 0), 0);
  const realized = hs.reduce((s, h) => s + (h.realized_pnl || 0), 0);
  const parked = book.parked || [];
  const parkedPnL = parked.reduce((s, h) => s + (h.realized_pnl || 0), 0);

  el.innerHTML = `
    ${scorecard([
      { label: 'Enabled', value: String(hs.length), sm: true },
      { label: 'Allocated', value: fmtLakh(allocated), sm: true },
      { label: 'Realized', value: fmtInr(Math.round(realized), true), sm: true, cls: pnlClass(realized) },
      { label: 'Parked (off)', value: String(parked.length) + ' · ' + fmtInr(Math.round(parkedPnL), true), sm: true, cls: pnlClass(parkedPnL) },
    ])}
    <div class="table-wrap" style="margin-top:16px">
      <table class="data">
        <thead><tr>
          <th>Algo</th><th>Mode</th><th class="num">Allocated</th><th class="num">Realized</th><th class="num">On capital</th>
        </tr></thead>
        <tbody>
          ${hs.map(h => {
            const pct = h.allocated ? 100 * (h.realized_pnl || 0) / h.allocated : 0;
            return `<tr data-id="${escapeHtml(h.id)}">
              <td><a href="#/algo/${encodeURIComponent(h.id)}">${escapeHtml(h.name)}</a>
                <div class="muted" style="font-size:.7rem">${escapeHtml(h.category || '')}</div></td>
              <td><span class="tag ${h.mode === 'manual' ? 'tag-ob' : 'tag-cs'}">${escapeHtml((h.mode || '').toUpperCase())}</span></td>
              <td class="num">${fmtLakh(h.allocated)}</td>
              <td class="num ${pnlClass(h.realized_pnl)}">${fmtInr(Math.round(h.realized_pnl || 0), true)}</td>
              <td class="num ${pnlClass(pct)}">${fmtPct(pct, 1, true)}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>
    ${parked.length ? `<p class="muted" style="margin-top:12px;font-size:.78rem">Parked (disabled on Stratzy, capital still showing):
      ${parked.map(p => `<a href="#/algo/${encodeURIComponent(p.id)}">${escapeHtml(p.name)}</a> ${fmtInr(Math.round(p.realized_pnl || 0), true)}`).join(' · ')}</p>` : ''}
  `;
}
