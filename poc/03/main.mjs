// POC-3: what is the real compile latency of assembleECharts()?
import { assembleECharts } from 'flint-chart/echarts';
import { writeFileSync } from 'node:fs';

const rows = [];
for (let m = 1; m <= 12; m++)
  for (const r of ['East', 'West', 'North'])
    rows.push({ month: `2026-${String(m).padStart(2, '0')}`, region: r,
      revenue: Math.round(1000 + 420 * Math.sin(m / 2) + (r === 'East' ? 300 : r === 'West' ? 150 : 0)) });

const base = { data: { values: rows }, semantic_types: { month: 'YearMonth', region: 'Country', revenue: 'Amount' } };
const TYPES = ['Bar Chart', 'Grouped Bar Chart', 'Stacked Bar Chart', 'Line Chart', 'Area Chart'];
const inputs = TYPES.map((t) => ({ ...base, chart_spec: { chartType: t, title: 'Revenue by month', encodings: { x: 'month', y: 'revenue', color: 'region' } } }));

const N = 200, WARM = 5;
for (let i = 0; i < WARM; i++) assembleECharts(inputs[i % inputs.length]);   // warm-up, not measured

const t = [];
for (let i = 0; i < N; i++) {
  const input = inputs[i % inputs.length];
  const a = process.hrtime.bigint();
  assembleECharts(input);
  const b = process.hrtime.bigint();
  t.push(Number(b - a) / 1e6);
}
// nearest-rank percentile (deterministic, no interpolation)
const sorted = [...t].sort((x, y) => x - y);
const pct = (p) => sorted[Math.ceil((p / 100) * sorted.length) - 1];

const res = {
  meta: { flint: '0.5.1', node: process.version, n: N, warmup: WARM, percentile: 'nearest-rank' },
  p50: +pct(50).toFixed(2), p95: +pct(95).toFixed(2), p99: +pct(99).toFixed(2),
  max: +Math.max(...t).toFixed(2), mean: +(t.reduce((a, b) => a + b, 0) / N).toFixed(2),
  min: +Math.min(...t).toFixed(2),
  frame_budget_pct: +((pct(95) / 16.7) * 100).toFixed(1),
};
writeFileSync('latency.json', JSON.stringify(res, null, 2));
console.log(JSON.stringify(res, null, 1));
