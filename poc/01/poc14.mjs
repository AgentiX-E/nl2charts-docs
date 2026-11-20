import * as duckdb from '@duckdb/duckdb-wasm';
import Worker from 'web-worker';
import { DuckDBInstance } from '@duckdb/node-api';

const dist = '/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';
const MANUAL = {
  mvp: { mainModule: `${dist}/duckdb-mvp.wasm`, mainWorker: `${dist}/duckdb-node-mvp.worker.cjs` },
  eh: { mainModule: `${dist}/duckdb-eh.wasm`, mainWorker: `${dist}/duckdb-node-eh.worker.cjs` },
};

const PROBES = [
  ['lambda_arrow', `SELECT list_transform([1,2,3], x -> x + 1) AS r`],
  ['lambda_python', `SELECT list_transform([1,2,3], lambda x : x + 1) AS r`],
  ['variant_type', `SELECT variant_type('{"a":1}'::JSON::VARIANT) AS r`],
  ['json_serialize_sql', `SELECT json_serialize_sql('SELECT 1') AS r`],
  ['decimal38', `SELECT (1::DECIMAL(38,10) * 2)::VARCHAR AS r`],
  ['timestamptz', `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+08', '%Y-%m-%dT%H:%M:%S%z') AS r`],
  ['qualify', `SELECT 1 AS x QUALIFY row_number() OVER () = 1`],
  ['pivot', `PIVOT (SELECT 'a' AS k, 1 AS v) ON k USING sum(v)`],
  ['grouping_sets', `SELECT a, b, count(*) FROM (SELECT 1 a, 2 b) t GROUP BY GROUPING SETS ((a),(b)) ORDER BY 1,2`],
  ['union_by_name', `SELECT 1 AS a UNION BY NAME SELECT 2 AS a`],
  ['summarize', `SUMMARIZE SELECT 1 AS a, 'x' AS b`],
  ['string_agg_order', `SELECT string_agg(DISTINCT x, ',' ORDER BY x) FROM (VALUES ('b'),('a')) t(x)`],
  ['list_comprehension', `SELECT [x*2 FOR x IN [1,2,3] IF x > 1] AS r`],
  ['struct_access', `SELECT struct_pack(a := 1, b := 'x').a AS r`],
  ['map_type', `SELECT MAP {'a': 1}['a'] AS r`],
  ['filter_clause', `SELECT count(*) FILTER (WHERE x > 1) FROM (VALUES (1),(2)) t(x)`],
  ['window_clause', `SELECT sum(x) OVER w FROM (VALUES (1),(2)) t(x) WINDOW w AS (ORDER BY x)`],
  ['asof_join', `SELECT count(*) FROM (VALUES (1)) a(t) ASOF JOIN (VALUES (1)) b(t) USING (t)`],
  ['attach_memory', `ATTACH ':memory:' AS m2`],
  ['install_postgres', `INSTALL postgres`],
  ['read_parquet_available', `SELECT count(*) FROM duckdb_functions() WHERE function_name = 'read_parquet'`],
  ['copy_to', `COPY (SELECT 1) TO '/tmp/poc14/x.csv'`],
  ['secret', `CREATE SECRET s (TYPE postgres, HOST 'x', PASSWORD 'y')`],
];

const DIFF_QUERIES = [
  ['agg', `SELECT status, count(*) n, sum(amount)::VARCHAR s FROM orders GROUP BY 1 ORDER BY 1`],
  ['decimal_precision', `SELECT (sum(amount))::VARCHAR s FROM orders`],
  ['tz_bucket', `SELECT strftime(date_trunc('month', created_at), '%Y-%m') m, count(*) n FROM orders GROUP BY 1 ORDER BY 1`],
  ['json_field', `SELECT payload->>'channel' ch, count(*) n FROM orders GROUP BY 1 ORDER BY 1`],
  ['json_type', `SELECT json_type(payload) t, count(*) n FROM orders GROUP BY 1`],
  ['array_len', `SELECT sum(len(tags)) n FROM orders`],
  ['array_unnest', `SELECT count(*) n FROM (SELECT unnest(tags) t FROM orders) x`],
  ['window_rank', `SELECT count(*) n FROM (SELECT order_id, row_number() OVER (PARTITION BY status ORDER BY amount DESC) rn FROM orders) x WHERE rn <= 3`],
  ['cte', `WITH a AS (SELECT status, amount FROM orders) SELECT status, count(*) FROM a GROUP BY 1 ORDER BY 1`],
  ['union', `SELECT count(*) FROM (SELECT order_id FROM orders UNION SELECT order_id FROM orders) x`],
  ['case_when', `SELECT sum(CASE WHEN amount > 500 THEN 1 ELSE 0 END) n FROM orders`],
  ['coalesce', `SELECT count(*) FILTER (WHERE coalesce(payload->>'channel','') = '') n FROM orders`],
  ['nullif', `SELECT count(nullif(region_id, 1)) n FROM orders`],
  ['round', `SELECT round(avg(amount), 3)::VARCHAR a FROM orders`],
  ['having', `SELECT count(*) FROM (SELECT status FROM orders GROUP BY 1 HAVING count(*) > 100) x`],
  ['listagg', `SELECT string_agg(DISTINCT status, ',' ORDER BY status) s FROM orders`],
  ['date_diff', `SELECT sum(date_diff('day', created_at, TIMESTAMPTZ '2026-10-17 00:00:00+00')) n FROM orders`],
  ['qualify2', `SELECT count(*) FROM (SELECT order_id, row_number() OVER (PARTITION BY status ORDER BY amount) rn FROM orders QUALIFY rn = 1) x`],
  ['interval', `SELECT count(*) n FROM orders WHERE created_at >= TIMESTAMPTZ '2026-10-17 00:00:00+00' - INTERVAL 30 DAY`],
  ['join_lateral', `SELECT count(*) FROM (SELECT o.order_id, d.region_name FROM orders o, LATERAL (SELECT region_name FROM dim_region WHERE region_id = o.region_id) d) x`],
];

const SETUP = `
CREATE TABLE dim_region (region_id INT, region_name VARCHAR, country VARCHAR);
INSERT INTO dim_region VALUES (1,'r1','CN'),(2,'r2','US'),(3,'r3','CN');
CREATE TABLE orders (order_id BIGINT, region_id INT, amount DECIMAL(12,2), status VARCHAR,
  created_at TIMESTAMPTZ, payload JSON, tags VARCHAR[]);
INSERT INTO orders VALUES
 (1,1,100.10,'paid','2026-09-01 10:00:00+00','{"channel":"web"}',['a','b']),
 (2,2,200.20,'paid','2026-09-15 11:00:00+00','{"channel":"app"}',['c']),
 (3,3,300.30,'refunded','2026-10-01 12:00:00+00','{"channel":"web"}',['a']),
 (4,1,400.40,'pending','2026-10-05 13:00:00+00','{"channel":"store"}',['b','c']),
 (5,2,500.50,'paid','2026-10-10 14:00:00+00','{"channel":"app"}',['a','b','c']);
`;

function norm(v) {
  if (typeof v === 'bigint') return v.toString();
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(6);
  if (v === null || v === undefined) return null;
  return String(v);
}
const rowKey = (rows) => JSON.stringify(rows.map(r => Object.values(r).map(norm)));

(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const nat = await inst.connect();
  const bundle = await duckdb.selectBundle(MANUAL);
  const worker = new Worker(bundle.mainWorker);
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  const wconn = await db.connect();

  const T = (p, ms = 8000) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('TIMEOUT')), ms))]);
  const natV = (await T(nat.runAndReadAll('SELECT version()'))).getRows()[0][0];
  const wasmV = (await wconn.query('SELECT version() AS v')).toArray()[0].v;
  console.log('NODE_VERSION', natV);
  console.log('WASM_VERSION', wasmV);

  // probe matrix
  const probeRes = [];
  for (const [name, sql] of PROBES) {
    let n = 'ok', w = 'ok';
    try { await T(nat.run(sql)); } catch (e) { n = String(e.message).slice(0, 70); }
    try { await T(wconn.query(sql)); } catch (e) { w = String(e.message).slice(0, 70); }
    probeRes.push({ name, node: n, wasm: w, same: (n === 'ok') === (w === 'ok') });
    console.log(`[probe:${name}] node=${n === 'ok' ? 'ok' : 'ERR'} wasm=${w === 'ok' ? 'ok' : 'ERR'} same=${(n === 'ok') === (w === 'ok')}`);
  }

  // differential results
  await nat.run(SETUP);
  for (const stmt of SETUP.split(';').map(s => s.trim()).filter(Boolean)) {
    await wconn.query(stmt);
  }
  const diff = [];
  for (const [name, sql] of DIFF_QUERIES) {
    let a, b, ea = null, eb = null;
    try { a = (await T(nat.runAndReadAll(sql))).getRowObjects().map(o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === 'bigint' ? v.toString() : v]))); } catch (e) { ea = String(e.message).slice(0, 80); }
    try { b = (await T(wconn.query(sql))).toArray().map(r => r.toJSON ? r.toJSON() : r); } catch (e) { eb = String(e.message).slice(0, 80); }
    const same = !ea && !eb && rowKey(a) === rowKey(b);
    diff.push({ name, same, ea, eb, node: rowKey(a || []), wasm: rowKey(b || []) });
    console.log(`[diff:${name}] same=${same} ${ea ? 'NODE_ERR:' + ea : ''} ${eb ? 'WASM_ERR:' + eb : ''}`);
    if (!same && !ea && !eb) console.log('   node=', rowKey(a), '\n   wasm=', rowKey(b));
  }

  // does wasm accept node-only catalog SQL?
  let fedOnWasm = 'ok';
  try { await wconn.query('SELECT count(*) FROM pg.public.orders'); } catch (e) { fedOnWasm = String(e.message).slice(0, 90); }
  console.log('FEDERATED_SQL_ON_WASM', fedOnWasm);

  console.log(JSON.stringify({ summary: {
    probes: probeRes.length, probeDivergence: probeRes.filter(p => !p.same).map(p => p.name),
    diffs: diff.length, diffMismatch: diff.filter(d => !d.same).map(d => d.name),
    nodeOnlyProbes: probeRes.filter(p => p.node === 'ok' && p.wasm !== 'ok').map(p => p.name),
    wasmOnlyProbes: probeRes.filter(p => p.wasm === 'ok' && p.node !== 'ok').map(p => p.name),
  } }, null, 1));

  await wconn.close(); await db.terminate();
})().catch(e => { console.error('FAIL', e); process.exit(1); });
