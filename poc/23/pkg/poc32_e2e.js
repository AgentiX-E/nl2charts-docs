import * as duckdb from '@duckdb/duckdb-wasm';

const marks = {};
const mark = (k) => { marks[k] = +performance.now().toFixed(1); };
mark('module_start');

const qsp = new URLSearchParams(location.search);
const ENGINE = qsp.get('engine') || 'eh';
const NO_WASM = qsp.get('nowasm') === '1';
const bundle = await duckdb.selectBundle(ENGINE === 'mvp'
  ? { mvp: { mainModule: './duckdb-mvp.wasm', mainWorker: './duckdb-browser-mvp.worker.js' } }
  : { eh:  { mainModule: './duckdb-eh.wasm',  mainWorker: './duckdb-browser-eh.worker.js' } });
mark('bundle_selected');

if (NO_WASM) {
  // 渐进路径：先只用预聚合 JSON 出图，不碰 wasm
  const t = performance.now();
  const agg = await (await fetch('./agg.json')).json();
  marks.agg_fetch_ms = +(performance.now() - t).toFixed(1);
  const cats = [...new Set(agg.map(r => r.m))];
  const grps = [...new Set(agg.map(r => r.grp))].slice(0, 3);
  const series = grps.map(g => ({ name: 'g' + g, data: cats.map(c => { const h = agg.find(r => r.m === c && r.grp === g); return h ? h.s : 0; }) }));
  const t2 = performance.now();
  const svg = ChartLib.renderSVG({ mark: 'bar', categories: cats, series }, 720, 400);
  marks.chart_compile_ms = +(performance.now() - t2).toFixed(1);
  document.getElementById('c').innerHTML = svg;
  marks.dom_inserted = +performance.now().toFixed(1);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    marks.painted = +performance.now().toFixed(1);
    marks.engine = 'nowasm';
    window.__m = marks;
  }));
} else {
const worker = new Worker(bundle.mainWorker);
const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
mark('wasm_instantiated');

const t0 = performance.now();
const buf = new Uint8Array(await (await fetch('./data.parquet')).arrayBuffer());
marks.fetch_ms = +(performance.now() - t0).toFixed(1);
marks.parquet_bytes = buf.length;
mark('parquet_fetched');

await db.registerFileBuffer('data.parquet', buf);
mark('registered');

const conn = await db.connect();
const t1 = performance.now();
const tbl = await conn.query(`
  SELECT strftime(d,'%Y-%m') AS m, grp, sum(v) AS s
  FROM 'data.parquet' GROUP BY 1,2 ORDER BY 1,2
`);
marks.query_ms = +(performance.now() - t1).toFixed(1);
marks.result_rows = tbl.numRows;
mark('query_done');

// 取前 12 个分组做图
const rows = tbl.toArray().slice(0, 12);
const cats = [...new Set(rows.map(r => r.m))];
const series = [...new Set(rows.map(r => r.grp))].slice(0, 3).map(g => ({
  name: 'g' + g,
  data: cats.map(c => { const hit = rows.find(r => r.m === c && r.grp === g); return hit ? Number(hit.s) : 0; }),
}));
const spec = { mark: 'bar', categories: cats, series };
const t2 = performance.now();
const svg = ChartLib.renderSVG(spec, 720, 400);
marks.chart_compile_ms = +(performance.now() - t2).toFixed(1);
mark('svg_ready');

const el = document.getElementById('c');
el.innerHTML = svg;
marks.dom_inserted = +performance.now().toFixed(1);
requestAnimationFrame(() => requestAnimationFrame(() => {
  marks.painted = +performance.now().toFixed(1);
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const fcp = performance.getEntriesByName('first-contentful-paint')[0];
  marks.domContentLoaded = nav.domContentLoadedEventEnd ? +nav.domContentLoadedEventEnd.toFixed(1) : null;
  marks.fcp = fcp ? +fcp.startTime.toFixed(1) : null;
  marks.resource_count = performance.getEntriesByType('resource').length;
  marks.engine = ENGINE;
  window.__m = marks;
}));
}
