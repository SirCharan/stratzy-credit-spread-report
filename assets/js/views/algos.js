// algos.js — clubs Rankings + Universe into one "Algos" tab.
import { subTabs } from '../subnav.js';

export function render(root, params, query) {
  return subTabs(root, {
    label: 'Algos',
    items: [
      { id: 'rankings', label: 'Rankings', mod: './views/rankings.js' },
      { id: 'universe', label: 'Universe', mod: './views/universe.js' },
    ],
    query,
  });
}
