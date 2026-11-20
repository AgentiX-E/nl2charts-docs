// deterministic chart selection: profiling -> candidate -> rank. no model involved.
export function recommend(rows) {
  const numeric = Object.keys(rows[0] ?? {}).filter((k) => typeof rows[0][k] === 'number');
  const categorical = Object.keys(rows[0] ?? {}).filter((k) => typeof rows[0][k] === 'string');
  const type = categorical.length && numeric.length ? 'bar' : numeric.length > 1 ? 'scatter' : 'table';
  return { type, x: categorical[0] ?? numeric[0], y: numeric[0], rowCount: rows.length };
}
export function compile(ir) { return { series: [{ type: ir.type, data: [] }], xAxis: { field: ir.x }, yAxis: { field: ir.y } }; }
