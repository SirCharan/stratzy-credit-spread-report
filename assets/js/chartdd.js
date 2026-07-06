// chartdd.js — shared drawdown shading for Chart.js equity curves.
// Underwater = below the running peak of a cumulative series.

const DD_FILL = 'rgba(224,88,79,0.10)';
export const DD_RED = '#E0584F';

// cumulative [{x,y}] -> underwater boolean per point
export function underwaterFlags(series) {
  let peak = -Infinity;
  return series.map(p => { peak = Math.max(peak, p.y); return p.y < peak - 1e-9; });
}

// cumulative [{x,y}] -> [[startX,endX], ...] underwater date ranges
export function underwaterRanges(series) {
  const ranges = []; let peak = -Infinity, start = null;
  for (const p of series) {
    if (p.y > peak - 1e-9) { peak = Math.max(peak, p.y); if (start) { ranges.push([start, p.x]); start = null; } }
    else if (!start) start = p.x;
  }
  if (start && series.length) ranges.push([start, series[series.length - 1].x]);
  return ranges;
}

// Chart.js plugin that shades red bands over underwater ranges.
// rangesFn() -> [[x,x],...]; enabledFn() -> bool (optional, defaults on).
let _bandSeq = 0;
export function ddBandPlugin(rangesFn, enabledFn, fill = DD_FILL) {
  return {
    id: 'ddBand' + (_bandSeq++),
    beforeDatasetsDraw(ch) {
      if (enabledFn && !enabledFn()) return;
      const ranges = rangesFn() || []; if (!ranges.length) return;
      const { ctx, chartArea: { top, bottom }, scales: { x } } = ch;
      ctx.save(); ctx.fillStyle = fill;
      for (const [a, b] of ranges) {
        const xa = x.getPixelForValue(a), xb = x.getPixelForValue(b);
        ctx.fillRect(xa, top, Math.max(xb - xa, 1), bottom - top);
      }
      ctx.restore();
    },
  };
}

// segment.borderColor callback: red while that dataset is underwater (reads dataset._under), else baseColor.
// enabledFn() -> bool (optional, defaults on).
export function ddSegment(baseColor, enabledFn) {
  return ctx => (
    (!enabledFn || enabledFn()) && ctx.p1DataIndex != null &&
    (ctx.chart.data.datasets[ctx.datasetIndex]._under || [])[ctx.p1DataIndex]
  ) ? DD_RED : baseColor;
}
