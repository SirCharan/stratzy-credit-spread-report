// studio.js — clubs Charts + Portfolio into one "Studio" tab (each keeps its own sub-tabs + ?tab).
import { subTabs } from '../subnav.js';

export function render(root, params, query) {
  return subTabs(root, {
    label: 'Studio',
    items: [
      { id: 'charts', label: 'Charts', mod: './views/charts.js' },
      { id: 'portfolio', label: 'Portfolio', mod: './views/portfolio.js' },
    ],
    query,
  });
}
