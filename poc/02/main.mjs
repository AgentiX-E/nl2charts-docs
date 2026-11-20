// POC-2: can assembleECharts() output actually be SSR-rendered, and what do its defaults do?
import { assembleECharts } from 'flint-chart/echarts';
import * as echarts from 'echarts';
import { writeFileSync } from 'node:fs';

// 36 rows = 12 months x 3 regions, deterministic (no randomness)
const REGIONS = ['East', 'West', 'North'];
const rows = [];
for (let m = 1; m <= 12; m++)
  for (const r of REGIONS)
    rows.push({
      month: `2026-${String(m).padStart(2, '0')}`,
      region: r,
      revenue: Math.round(1000 + 420 * Math.sin(m / 2) + (r === 'East' ? 300 : r === 'West' ? 150 : 0)),
    });

const base = {
  data: { values: rows },
  semantic_types: { month: 'YearMonth', region: 'Country', revenue: 'Amount' },
};

const CASES = [
  ['Bar Chart', { x: 'month', y: 'revenue', color: 'region' }],
  ['Grouped Bar Chart', { x: 'month', y: 'revenue', color: 'region' }],
  ['Stacked Bar Chart', { x: 'month', y: 'revenue', color: 'region' }],
  ['Line Chart', { x: 'month', y: 'revenue', color: 'region' }],
  ['Area Chart', { x: 'month', y: 'revenue', color: 'region' }],
  ['Scatter Plot', { x: 'month', y: 'revenue', color: 'region' }],
];

const strip = (o) => Object.fromEntries(Object.entries(o).filter(([k]) => !k.startsWith('_')));

function render(option) {
  const opt = strip(option);
  const w = Math.round(option._width ?? 600);
  const h = Math.round(option._height ?? 420);
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: w, height: h });
  chart.setOption(opt);
  const svg = chart.renderToSVGString();
  chart.dispose();
  const count = (re) => (svg.match(re) || []).length;
  return {
    width: w, height: h,
    bytes: Buffer.byteLength(svg, 'utf8'),
    paths: count(/<path\b/g),
    texts: count(/<text\b/g),
    rects: count(/<rect\b/g),
    svg,
  };
}

const out = { meta: { flint: '0.5.1', echarts: echarts.version, rows: rows.length }, cases: [] };
for (const [type, enc] of CASES) {
  const option = assembleECharts({ ...base, chart_spec: { chartType: type, title: 'Revenue by month', encodings: enc } });
  const series = option.series || [];
  const r = render(option);
  out.cases.push({
    type,
    seriesCount: series.length,
    seriesType: [...new Set(series.map((s) => s.type))].join('/'),
    stack: [...new Set(series.map((s) => s.stack ?? null))],
    kb: +(r.bytes / 1024).toFixed(1),
    paths: r.paths, texts: r.texts, rects: r.rects,
    render_ok: r.paths > 0 && r.texts > 0,
  });
  writeFileSync(`svg-${type.replace(/\s+/g, '-').toLowerCase()}.svg`, r.svg);
}

// does chart_spec.stack get honoured?
const gb = assembleECharts({ ...base, chart_spec: { chartType: 'Grouped Bar Chart', encodings: { x: 'month', y: 'revenue', color: 'region' }, stack: true } });
out.stack_flag_ignored = gb.series.every((s) => (s.stack ?? null) === null);
// does an unknown chartType fail loudly?
try { assembleECharts({ ...base, chart_spec: { chartType: 'Nope Chart', encodings: { x: 'month' } } }); out.unknown_type = 'accepted'; }
catch (e) { out.unknown_type = 'throws: ' + String(e.message).slice(0, 80); }

writeFileSync('results.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify({ cases: out.cases.map(c => [c.type, c.kb, c.paths, c.texts, c.rects, c.stack.join()]), stack_flag_ignored: out.stack_flag_ignored, unknown_type: out.unknown_type }, null, 1));
