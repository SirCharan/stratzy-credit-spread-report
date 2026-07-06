// playbook.js — clubs Field Guide + Regime into one "Playbook" tab.
import { subTabs } from '../subnav.js';

export function render(root, params, query) {
  return subTabs(root, {
    label: 'Playbook',
    items: [
      { id: 'guide', label: 'Field Guide', mod: './views/guide.js' },
      { id: 'regime', label: 'Regime', mod: './views/regime.js' },
    ],
    query,
  });
}
