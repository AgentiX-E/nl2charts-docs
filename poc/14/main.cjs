const path = '/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';
const { createDuckDB, NODE_RUNTIME, ConsoleLogger, PACKAGE_VERSION } = require(path + '/duckdb-node-blocking.cjs');
const { DuckDBInstance } = require('/tmp/poc1/node_modules/@duckdb/node-api');

const PROBES = [
  ['lambda_arrow', `SELECT list_transform([1,2,3], x -> x + 1) AS r`],
  ['lambda_python', `SELECT list_transform([1,2,3], lambda x : x + 1) AS r`],
  ['variant_type', `SELECT variant_type('{"a":1}'::JSON::VARIANT) AS r`],
  ['json_serialize_sql', `SELECT json_serialize_sql('SELECT 1') AS r`],
  ['decimal38', `SELECT (1::DECIMAL(38,10) * 2)::VARCHAR AS r`],
  ['timestamptz', `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+08', '%Y-%m-%dT%H:%M:%S%z') AS r`],
  ['qualify', `SELECT 1 AS x QUALIFY row_number() OVER () = 1`],
  ['pivot', `PIVOT (SELECT 'a' AS k, 1 AS v) ON k USING sum(v)`],
  ['grouping_sets', `SELECT a, b, count(*) c FROM (SELECT 1 a, 2 b) t GROUP BY GROUPING SETS ((a),(b)) ORDER BY 1,2`],
  ['union_by_name', `SELECT 1 AS a UNION BY NAME SELECT 2 AS a`],
  ['summarize', `SUMMARIZE SELECT 1 AS a, 'x' AS b`],
  ['string_agg_order', `SELECT string_agg(DISTINCT x, ',' ORDER BY x) s FROM (VALUES ('b'),('a')) t(x)`],
  ['list_comprehension', `SELECT [x*2 FOR x IN [1,2,3] IF x > 1] AS r`],
  ['struct_access', `SELECT struct_pack(a := 1, b := 'x').a AS r`],
  ['map_type', `SELECT MAP {'a': 1}['a'] AS r`],
  ['filter_clause', `SELECT count(*) FILTER (WHERE x > 1) c FROM (VALUES (1),(2)) t(x)`],
  ['window_clause', `SELECT sum(x) OVER w s FROM (VALUES (1),(2)) t(x) WINDOW w AS (ORDER BY x)`],
  ['asof_join', `SELECT count(*) c FROM (VALUES (1)) a(t) ASOF JOIN (VALUES (1)) b(t) USING (t)`],
  ['json_type_fn', `SELECT json_type('{"a":1}') AS r`],
  ['read_parquet_fn', `SELECT count(*) c FROM duckdb_functions() WHERE function_name = 'read_parquet'`],
  ['read_csv_fn', `SELECT count(*) c FROM duckdb_functions() WHERE function_name = 'read_csv'`],
  ['unnest', `SELECT count(*) c FROM (SELECT unnest([1,2,3])) t(x)`],
  ['range_fn', `SELECT count(*) c FROM range(5)`],
  ['pivot_longer', `SELECT count(*) c FROM (PIVOT (SELECT 'a' k, 1 v) ON k USING sum(v)) p`],
  ['secret_syntax', `CREATE SECRET s (TYPE postgres, HOST 'x', PASSWORD 'y')`],
];

const DIFF = [
  ['agg', `SELECT status, count(*) n, sum(amount)::VARCHAR s FROM orders GROUP BY 1 ORDER BY 1`],
  ['decimal_precision', `SELECT sum(amount)::VARCHAR s FROM orders`],
  ['tz_bucket', `SELECT strftime(date_trunc('month', created_at), '%Y-%m') m, count(*) n FROM orders GROUP BY 1 ORDER BY 1`],
  ['json_field', `SELECT payload->>'channel' ch, count(*) n FROM orders GROUP BY 1 ORDER BY 1`],
  ['json_type', `SELECT json_type(payload) t, count(*) n FROM orders GROUP BY 1`],
  ['array_len', `SELECT sum(len(tags)) n FROM orders`],
  ['array_unnest', `SELECT count(*) n FROM (SELECT unnest(tags) t FROM orders) x`],
  ['window_rank', `SELECT count(*) n FROM (SELECT order_id, row_number() OVER (PARTITION BY status ORDER BY amount DESC) rn FROM orders) x WHERE rn <= 3`],
  ['cte', `WITH a AS (SELECT status, amount FROM orders) SELECT status, count(*) c FROM a GROUP BY 1 ORDER BY 1`],
  ['union', `SELECT count(*) c FROM (SELECT order_id FROM orders UNION SELECT order_id FROM orders) x`],
  ['case_when', `SELECT sum(CASE WHEN amount > 500 THEN 1 ELSE 0 END) n FROM orders`],
  ['coalesce', `SELECT count(*) FILTER (WHERE coalesce(payload->>'channel','') = '') n FROM orders`],
  ['nullif', `SELECT count(nullif(region_id, 1)) n FROM orders`],
  ['round', `SELECT round(avg(amount), 3)::VARCHAR a FROM orders`],
  ['having', `SELECT count(*) c FROM (SELECT status FROM orders GROUP BY 1 HAVING count(*) > 1) x`],
  ['listagg', `SELECT string_agg(DISTINCT status, ',' ORDER BY status) s FROM orders`],
  ['date_diff', `SELECT sum(date_diff('day', created_at, TIMESTAMPTZ '2026-10-17 00:00:00+00')) n FROM orders`],
  ['qualify2', `SELECT count(*) c FROM (SELECT order_id, row_number() OVER (PARTITION BY status ORDER BY amount) rn FROM orders QUALIFY rn = 1) x`],
  ['interval_arith', `SELECT count(*) n FROM orders WHERE created_at >= TIMESTAMPTZ '2026-10-17 00:00:00+00' - INTERVAL 30 DAY`],
  ['lateral', `SELECT count(*) c FROM (SELECT o.order_id, d.region_name FROM orders o, LATERAL (SELECT region_name FROM dim_region WHERE region_id = o.region_id) d) x`],
  ['except_all', `SELECT count(*) c FROM ((SELECT status FROM orders) EXCEPT ALL (SELECT status FROM orders)) x`],
  ['intersect', `SELECT count(*) c FROM ((SELECT status FROM orders) INTERSECT (SELECT status FROM orders)) x`],
  ['grouping_fn', `SELECT grouping(status) g, count(*) c FROM orders GROUP BY ROLLUP(status) ORDER BY 1`],
  ['filter_push', `SELECT count(*) c FROM orders WHERE created_at >= TIMESTAMPTZ '2026-10-01 00:00:00+00' AND status IN ('paid','pending')`],
];

const SETUP = [
  `CREATE TABLE dim_region (region_id INT, region_name VARCHAR, country VARCHAR)`,
  `INSERT INTO dim_region VALUES (1,'r1','CN'),(2,'r2','US'),(3,'r3','CN')`,
  `CREATE TABLE orders (order_id BIGINT, region_id INT, amount DECIMAL(12,2), status VARCHAR, created_at TIMESTAMPTZ, payload JSON, tags VARCHAR[])`,
  `INSERT INTO orders VALUES
   (1,1,100.10,'paid','2026-09-01 10:00:00+00','{"channel":"web"}',['a','b']),
   (2,2,200.20,'paid','2026-09-15 11:00:00+00','{"channel":"app"}',['c']),
   (3,3,300.30,'refunded','2026-10-01 12:00:00+00','{"channel":"web"}',['a']),
   (4,1,400.40,'pending','2026-10-05 13:00:00+00','{"channel":"store"}',['b','c']),
   (5,2,500.50,'paid','2026-10-10 14:00:00+00','{"channel":"app"}',['a','b','c'])`,
];

const norm = (v) => {
  if (typeof v === 'bigint') return v.toString();
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(6)));
  if (v === null || v === undefined) return null;
  if (typeof v === 'object' && v.constructor && v.constructor.name === 'BigInt') return v.toString();
  return String(v);
};
const key = (rows) => JSON.stringify(rows.map(r => Object.values(r).map(norm)));

(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const nat = await inst.connect();
  const db = await createDuckDB({ mvp: { mainModule: path + '/duckdb-mvp.wasm' }, eh: { mainModule: path + '/duckdb-eh.wasm' } }, new ConsoleLogger(), NODE_RUNTIME);
  await db.instantiate();
  const w = db.connect();

  const nv = (await nat.runAndReadAll('SELECT version()')).getRows()[0][0];
  const wv = w.query('SELECT version() v').toArray()[0].v;
  console.log(`NODE ${nv} | WASM ${wv} | duckdb-wasm pkg ${PACKAGE_VERSION}`);

  const probes = [];
  for (const [name, sql] of PROBES) {
    let n = 'ok', ww = 'ok';
    try { await nat.run(sql); } catch (e) { n = String(e.message).split('\n')[0].slice(0, 90); }
    try { w.query(sql); } catch (e) { ww = String(e.message).split('\n')[0].slice(0, 90); }
    const same = (n === 'ok') === (ww === 'ok');
    probes.push({ name, node: n, wasm: ww, same });
    if (!same) console.log(`[probe:${name}] node=${n === 'ok' ? 'ok' : 'ERR'} wasm=${ww === 'ok' ? 'ok' : 'ERR'}`);
  }
  console.log('PROBE_DIVERGENCE', probes.filter(p => !p.same).map(p => `${p.name}(node=${p.node === 'ok' ? 'ok' : 'ERR'},wasm=${p.wasm === 'ok' ? 'ok' : 'ERR'})`).join(', ') || 'none');

  for (const s of SETUP) { await nat.run(s); w.query(s); }

  const diffs = [];
  for (const [name, sql] of DIFF) {
    let a, b, ea = null, eb = null;
    try { a = (await nat.runAndReadAll(sql)).getRowObjects(); } catch (e) { ea = String(e.message).split('\n')[0].slice(0, 90); }
    try { b = w.query(sql).toArray().map(r => r.toJSON ? r.toJSON() : r); } catch (e) { eb = String(e.message).split('\n')[0].slice(0, 90); }
    const same = !ea && !eb && key(a) === key(b);
    diffs.push({ name, same, ea, eb, node: key(a || []), wasm: key(b || []) });
    if (!same) console.log(`[diff:${name}] same=false ${ea ? 'NODE_ERR:' + ea : ''} ${eb ? 'WASM_ERR:' + eb : ''}`);
    if (!same && !ea && !eb) console.log('   node=', key(a), '\n   wasm=', key(b));
  }
  console.log('DIFF_MISMATCH', diffs.filter(d => !d.same).map(d => d.name).join(', ') || 'none', `(${diffs.filter(d => d.same).length}/${diffs.length} same)`);

  require('fs').writeFileSync('/tmp/poc14/results.json', JSON.stringify({ nv, wv, probes, diffs }, (k, v) => typeof v === 'bigint' ? v.toString() : v, 2));
})().catch(e => { console.error('FAIL', e); process.exit(1); });
