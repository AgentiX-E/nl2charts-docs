import { echarts } from './chart-entry.js';

// minimal ChartIR -> ECharts option (deterministic, no LLM)
export function compile(spec) {
  const base = {
    animation: false,
    grid: { left: 48, right: 24, top: 32, bottom: 40, containLabel: true },
    tooltip: { trigger: spec.mark === 'pie' ? 'item' : 'axis' },
    legend: spec.series.length > 1 ? { top: 0 } : undefined,
    xAxis: spec.mark === 'pie' ? undefined : { type: spec.xType || 'category', data: spec.categories },
    yAxis: spec.mark === 'pie' ? undefined : { type: 'value' },
  };
  if (spec.mark === 'pie') {
    return { ...base, series: [{ type: 'pie', radius: ['30%', '65%'], data: spec.series[0].data }] };
  }
  return { ...base, series: spec.series.map(s => ({ type: spec.mark, name: s.name, data: s.data, smooth: spec.mark === 'line' })) };
}

export function renderSVG(spec, width = 640, height = 360) {
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width, height });
  chart.setOption(compile(spec));
  const svg = chart.renderToSVGString();
  chart.dispose();
  return svg;
}
