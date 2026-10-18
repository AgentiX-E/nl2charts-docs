// POC-2b: chart-type capability matrix across five flint-chart backends
import * as F from 'flint-chart';
import { writeFileSync } from 'node:fs';

const flat = (v) => (Array.isArray(v) ? v.flat(3) : Object.values(v).flat(3));
const toNames = (v) => flat(v).map((d) => d && (d.chart ?? d.name ?? d.chartType ?? d.id)).filter(Boolean).sort();

const backends = {
  echarts: toNames(F.ecAllTemplateDefs),
  vegalite: toNames(F.vlAllTemplateDefs),
  chartjs: toNames(F.cjsAllTemplateDefs),
  plotly: toNames(F.plTemplateDefs),
  excel: toNames(F.excelAllTemplateDefs),
};
const union = [...new Set(Object.values(backends).flat())].sort();
const inter = Object.values(backends).reduce((a, b) => a.filter((x) => b.includes(x)));

console.log('per-backend:', Object.fromEntries(Object.entries(backends).map(([k, v]) => [k, v.length])));
console.log('union', union.size ?? union.length, 'intersection', inter.length);
console.log('intersection:', inter.join(', '));
writeFileSync('matrix.json', JSON.stringify({ counts: Object.fromEntries(Object.entries(backends).map(([k, v]) => [k, v.length])), union: union.length, intersection: inter.length, intersection_names: inter, per_backend: backends }, null, 1));
