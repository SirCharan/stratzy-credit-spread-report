// cmdk.js — ⌘K command palette. App supplies a getCommands(query) provider.

import { $, escapeHtml } from './util.js';

let provider = () => [];
let items = [];
let sel = 0;

const scrim = () => $('#cmdk-scrim');
const input = () => $('#cmdk-input');
const list = () => $('#cmdk-list');

export function init(getCommands) {
  provider = getCommands;
  $('#cmdk-open')?.addEventListener('click', open);
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); toggle(); }
    else if (e.key === 'Escape' && scrim().classList.contains('open')) close();
    else if (scrim().classList.contains('open')) {
      if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter') { e.preventDefault(); run(sel); }
    }
  });
  scrim().addEventListener('click', e => { if (e.target === scrim()) close(); });
  input().addEventListener('input', render);
  list().addEventListener('click', e => {
    const it = e.target.closest('.cmdk-item'); if (it) run(+it.dataset.i);
  });
}

function toggle() { scrim().classList.contains('open') ? close() : open(); }
function open() { scrim().classList.add('open'); input().value = ''; sel = 0; render(); input().focus(); }
function close() { scrim().classList.remove('open'); }
function move(d) { sel = Math.max(0, Math.min(items.length - 1, sel + d)); paint(); }

function render() {
  items = provider(input().value.trim());
  sel = Math.min(sel, Math.max(0, items.length - 1));
  let html = ''; let lastGroup = null;
  items.forEach((it, i) => {
    if (it.group !== lastGroup) { html += `<div class="cmdk-group">${escapeHtml(it.group)}</div>`; lastGroup = it.group; }
    html += `<div class="cmdk-item" data-i="${i}">${escapeHtml(it.label)}${it.hint ? `<span class="k">${escapeHtml(it.hint)}</span>` : ''}</div>`;
  });
  list().innerHTML = html || `<div class="cmdk-group">No matches</div>`;
  paint();
}
function paint() {
  [...list().querySelectorAll('.cmdk-item')].forEach((el, i) => {
    el.classList.toggle('sel', i === sel);
    if (i === sel) el.scrollIntoView({ block: 'nearest' });
  });
}
function run(i) { const it = items[i]; if (it) { close(); it.run(); } }
