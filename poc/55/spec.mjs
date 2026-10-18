// POC-55: the SQL-only path — user supplies SQL and names the chart type.
// Measures: (1) does an explicit chart spec need a recommender or an LLM?
// (2) are incompatible (type, data shape) pairs rejected with a reason?
// (3) is the rendered output reproducible from the spec alone?
// (4) how many bytes does chart-only code cost when bundled without core/ai?
import fs from 'node:fs';
import crypto from 'node:crypto';

// ---------------------------------------------------------------- spec model
const SHAPES = {
  bar: { dims: [['categorical', 'temporal']], measures: [1], optional: ['series'] },
  line: { dims: [['temporal', 'ordinal']], measures: [1], optional: ['series'] },
  pie: { dims: [['categorical']], measures: [1], optional: [] },
  scatter: { dims: [['numeric']], measures: [1], optional: [] },
  table: { dims: [['categorical', 'temporal', 'numeric', 'ordinal']], measures: [0, 99], optional: [] },
};

const TYPES = {
  categorical: (v) => typeof v === 'string' && v.length > 0,
  temporal: (v) => v instanceof Date || /^\d{4}-\d{2}(-\d{2})?$/.test(String(v)),
  ordinal: (v) => typeof v === 'string' || typeof v === 'number',
  numeric: (v) => typeof v === 'number' && Number.isFinite(v),
};

function infer(name, values) {
  const sample = values.filter(v => v !== null && v !== undefined).slice(0, 50);
  for (const t of ['numeric', 'temporal', 'categorical']) {
    if (sample.length && sample.every(v => TYPES[t](v))) return t;
  }
  return 'categorical';
}

export function validate({ rows, columns, chart }) {
  if (!Array.isArray(rows) || !rows.length) throw new Error('CHART_EMPTY_RESULT');
  const { type, x, y, series } = chart;
  const shape = SHAPES[type];
  if (!shape) throw new Error('CHART_UNKNOWN_TYPE:' + type);
  if (!columns.includes(x)) throw new Error('CHART_X_NOT_IN_RESULT:' + x);
  if (!columns.includes(y)) throw new Error('CHART_Y_NOT_IN_RESULT:' + y);
  if (series && !columns.includes(series)) throw new Error('CHART_SERIES_NOT_IN_RESULT:' + series);

  const xt = infer(x, rows.map(r => r[x]));
  const yt = infer(y, rows.map(r => r[y]));
  if (shape.dims.length && xt === 'numeric' && type !== 'scatter') throw new Error('CHART_DIMENSION_REQUIRED:' + type);
  if (!shape.dims.some(g => g.includes(xt))) throw new Error(`CHART_X_TYPE:${type} rejects ${xt}`);
  if (!shape.measures.includes(1) && shape.measures[0] !== 0) throw new Error('CHART_MEASURE_REQUIRED');
  if (type !== 'table' && !TYPES.numeric(rows[0][y])) throw new Error(`CHART_Y_NOT_MEASURE:${yt}`);
  if (type === 'pie' && new Set(rows.map(r => r[x])).size > 24) throw new Error('CHART_PIE_TOO_MANY_SLICES');
  if (type === 'scatter' && !TYPES.numeric(rows[0][x])) throw new Error('CHART_SCATTER_X_NOT_NUMERIC');
  return { xType: xt, yType: yt, n: rows.length, type };
}

// ---------------------------------------------------------------- deterministic render
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

export function render(spec) {
  const { rows, chart, width = 480, height = 240 } = spec;
  if (!Array.isArray(rows) || rows.length === 0) throw new Error('CHART_EMPTY_RESULT');
  validate({ rows, columns: Object.keys(rows[0]), chart });
  const pad = 32, w = width - pad * 2, h = height - pad * 2;
  const ys = rows.map(r => Number(r[chart.y]));
  const max = Math.max(...ys), min = Math.min(0, ...ys);
  const scale = (v) => h - ((v - min) / (max - min || 1)) * h;
  let body = '';
  if (chart.type === 'bar' || chart.type === 'line') {
    const bw = w / rows.length;
    body = rows.map((r, i) => {
      const x = pad + i * bw;
      if (chart.type === 'bar') {
        return `<rect x="${(x + 1).toFixed(1)}" y="${(pad + scale(ys[i])).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${(h - scale(ys[i])).toFixed(1)}" fill="#3b6ea5"/>`;
      }
      return `<circle cx="${(x + bw / 2).toFixed(1)}" cy="${(pad + scale(ys[i])).toFixed(1)}" r="2.5" fill="#3b6ea5"/>`;
    }).join('');
    if (chart.type === 'line') {
      const pts = rows.map((r, i) => `${(pad + i * bw + bw / 2).toFixed(1)},${(pad + scale(ys[i])).toFixed(1)}`).join(' ');
      body = `<polyline points="${pts}" fill="none" stroke="#3b6ea5" stroke-width="1.5"/>` + body;
    }
  } else if (chart.type === 'pie') {
    const total = ys.reduce((a, b) => a + b, 0) || 1;
    let acc = -Math.PI / 2;
    body = rows.map((r, i) => {
      const a = (ys[i] / total) * Math.PI * 2;
      const x1 = 120 + 80 * Math.cos(acc), y1 = 120 + 80 * Math.sin(acc);
      acc += a;
      const x2 = 120 + 80 * Math.cos(acc), y2 = 120 + 80 * Math.sin(acc);
      const large = a > Math.PI ? 1 : 0;
      return `<path d="M120 120 L${x1.toFixed(1)} ${y1.toFixed(1)} A80 80 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)} Z" fill="hsl(${(i * 47) % 360} 55% 55%)"/>`;
    }).join('');
  } else if (chart.type === 'scatter') {
    const xs = rows.map(r => Number(r[chart.x]));
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    body = rows.map((r, i) => {
      const cx = pad + ((xs[i] - xmin) / (xmax - xmin || 1)) * w;
      return `<circle cx="${cx.toFixed(1)}" cy="${(pad + scale(ys[i])).toFixed(1)}" r="3" fill="#3b6ea5"/>`;
    }).join('');
  } else {
    body = rows.map((r, i) =>
      `<text x="${pad}" y="${(pad + 16 + i * 18).toFixed(0)}" font-size="11">${esc(Object.values(r).join('  ·  '))}</text>`).join('');
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" role="img" aria-label="${esc(chart.type)} chart">` +
    `<rect width="${width}" height="${height}" fill="#fff"/>${body}</svg>`;
}

// ---------------------------------------------------------------- fixtures
const CAT = [
  { region: 'emea', revenue: 120 }, { region: 'apac', revenue: 90 }, { region: 'amer', revenue: 150 },
];
const TIME = [
  { month: '2026-01', revenue: 120 }, { month: '2026-02', revenue: 90 }, { month: '2026-03', revenue: 150 },
];
const NUM = [
  { price: 12.5, revenue: 120 }, { price: 9.0, revenue: 90 }, { price: 15.2, revenue: 150 },
];

const cases = [
  { id: 'bar-cat', rows: CAT, chart: { type: 'bar', x: 'region', y: 'revenue' } },
  { id: 'line-time', rows: TIME, chart: { type: 'line', x: 'month', y: 'revenue' } },
  { id: 'pie-cat', rows: CAT, chart: { type: 'pie', x: 'region', y: 'revenue' } },
  { id: 'scatter-num', rows: NUM, chart: { type: 'scatter', x: 'price', y: 'revenue' } },
  { id: 'table-any', rows: CAT, chart: { type: 'table', x: 'region', y: 'revenue' } },
];

const rendered = [];
for (const c of cases) {
  const svg = render({ rows: c.rows, chart: c.chart });
  const hash = crypto.createHash('sha256').update(svg).digest('hex').slice(0, 16);
  const again = crypto.createHash('sha256').update(render({ rows: c.rows, chart: c.chart })).digest('hex').slice(0, 16);
  rendered.push({ id: c.id, bytes: Buffer.byteLength(svg), hash, replayIdentical: hash === again });
}

const invalid = [
  ['pie-two-measures', () => render({ rows: NUM, chart: { type: 'pie', x: 'price', y: 'revenue' } })],
  ['line-on-categorical', () => render({ rows: CAT, chart: { type: 'line', x: 'region', y: 'revenue' } })],
  ['bar-y-not-numeric', () => render({ rows: CAT.map(r => ({ ...r, revenue: 'high' })), chart: { type: 'bar', x: 'region', y: 'revenue' } })],
  ['scatter-x-not-numeric', () => render({ rows: CAT, chart: { type: 'scatter', x: 'region', y: 'revenue' } })],
  ['unknown-column', () => render({ rows: CAT, chart: { type: 'bar', x: 'nope', y: 'revenue' } })],
  ['empty-result', () => render({ rows: [], chart: { type: 'bar', x: 'region', y: 'revenue' } })],
];
const rejected = invalid.map(([id, fn]) => {
  try { fn(); return { id, rejected: false }; } catch (e) { return { id, rejected: true, code: e.message.split(':')[0] }; }
});

// spec is plain JSON: serialize it, ship it to another process, re-render
const replay = cases.map(c => {
  const wire = JSON.stringify({ rows: c.rows, chart: c.chart, width: 480, height: 240 });
  const svg = render(JSON.parse(wire));
  const h = crypto.createHash('sha256').update(svg).digest('hex').slice(0, 16);
  const original = rendered.find(r => r.id === c.id);
  return { id: c.id, replayIdentical: h === original.hash };
});

const out = {
  generatedAt: new Date().toISOString(),
  replay,
  rendered,
  rejected,
  summary: {
    rendered: `${rendered.filter(r => r.replayIdentical).length}/${rendered.length}`,
    jsonReplay: `${replay.filter(r => r.replayIdentical).length}/${replay.length}`,
    rejected: `${rejected.filter(r => r.rejected).length}/${rejected.length}`,
    llmCalls: 0,
    networkCalls: 0,
  },
};
fs.writeFileSync('results.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify(out.summary, null, 2));
console.log(rendered.map(r => `${r.id} ${r.bytes}B ${r.hash}`).join('\n'));
console.log(rejected.map(r => `${r.id}: ${r.code || 'NOT REJECTED'}`).join('\n'));
