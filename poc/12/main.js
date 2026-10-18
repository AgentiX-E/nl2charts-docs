const { DuckDBInstance } = require('@duckdb/node-api');
const fs = require('fs');
const t0 = () => process.hrtime.bigint();
const ms = (a, b) => Number(b - a) / 1e6;

(async () => {
  const log = (k, v) => console.log(`[${k}]`, typeof v === 'object' ? JSON.stringify(v, (_, x) => typeof x === 'bigint' ? x.toString() : x) : v);
  const inst = await DuckDBInstance.create(':memory:');
  const c = await inst.connect();

  // 0) extensions
  let a = t0();
  await c.run('INSTALL postgres');
  await c.run('LOAD postgres');
  log('install_postgres_ms', ms(a, t0()).toFixed(0));

  a = t0();
  await c.run(`ATTACH 'host=127.0.0.1 port=5432 dbname=analytics user=t2c password=t2cpass connect_timeout=10'
               AS pg (TYPE postgres, READ_ONLY, SCHEMA 'public')`);
  log('attach_postgres_ms', ms(a, t0()).toFixed(0));

  // 1) catalog discovery
  const tabs = await c.runAndReadAll(`SELECT table_name FROM duckdb_tables() WHERE database_name='pg' ORDER BY 1`);
  log('pg_tables', tabs.getRows().map(r => r[0]).join(','));
  const cols = await c.runAndReadAll(`SELECT table_name, column_name, data_type FROM duckdb_columns() WHERE database_name='pg' AND table_name='orders'`);
  log('pg_orders_columns', cols.getRows().map(r => r.join(':')).join(' | '));

  // 2) pushdown evidence: let DuckDB print SQL sent to PG
  await c.run(`SET pg_debug_show_queries=true`);
  a = t0();
  const q1 = await c.runAndReadAll(`
    SELECT status, count(*) AS n, round(sum(amount),2) AS amt
    FROM pg.public.orders
    WHERE created_at >= TIMESTAMPTZ '2026-01-01 00:00:00+00' AND status='paid'
    GROUP BY status`);
  log('federated_agg_ms', ms(a, t0()).toFixed(0));
  log('federated_rows', q1.getRows());

  // 3) pushdown off
  await c.run(`SET pg_experimental_filter_pushdown=false`);
  a = t0();
  const q2 = await c.runAndReadAll(`
    SELECT status, count(*) AS n FROM pg.public.orders
    WHERE created_at >= TIMESTAMPTZ '2026-01-01 00:00:00+00' AND status='paid' GROUP BY status`);
  log('no_pushdown_ms', ms(a, t0()).toFixed(0));
  log('no_pushdown_rows', q2.getRows());
  await c.run(`SET pg_experimental_filter_pushdown=true`);

  // 4) cross-source join: local table + pg table
  await c.run(`CREATE TABLE local_region(region_id INT, owner TEXT)`);
  await c.run(`INSERT INTO local_region VALUES (1,'alice'),(2,'bob'),(3,'carol')`);
  const q3 = await c.runAndReadAll(`
    SELECT l.owner, count(*) n FROM pg.public.orders o
    JOIN local_region l USING(region_id) GROUP BY 1 ORDER BY n DESC`);
  log('cross_join_rows', q3.getRows());

  // 5) sqlite scanner + three-way federation
  try {
    await c.run('INSTALL sqlite'); await c.run('LOAD sqlite');
    await c.run(`ATTACH '/tmp/poc12/small.sqlite' AS sq (TYPE sqlite, READ_ONLY)`);
  } catch (e) { log('sqlite_attach_err', String(e.message).slice(0,200)); }
  log('databases', (await c.runAndReadAll('SHOW DATABASES')).getRows().map(r=>r[0]).join(','));
  const q4 = await c.runAndReadAll(`
    SELECT k.k, pg.public.dim_region.region_name
    FROM sq.t k JOIN pg.public.dim_region USING(region_id) LIMIT 3`);
  log('three_way_rows', q4.getRows());

  // 6) type mapping
  const q5 = await c.runAndReadAll(`SELECT * FROM pg.public.orders LIMIT 1`);
  log('type_mapping', q5.columnNames().map((n, i) => `${n}:${q5.columnTypes()[i].toString()}`).join(' | '));

  // 7) read-only enforcement
  let rw = 'ok';
  try { await c.run(`INSERT INTO pg.public.orders(order_id) VALUES (-1)`); rw = 'WROTE (bad)'; }
  catch (e) { rw = String(e.message).slice(0, 120); }
  log('read_only_enforced', rw);

  // 8) guard: AST of federated query
  const ast = await c.runAndReadAll(`SELECT json_serialize_sql('SELECT region_name, count(*) FROM pg.public.orders o JOIN pg.public.dim_region d USING(region_id) GROUP BY 1')`);
  const j = JSON.parse(ast.getRows()[0][0]);
  const names = [];
  (function walk(n) {
    if (!n || typeof n !== 'object') return;
    if (n.type === 'BASE_TABLE') names.push([n.catalog_name, n.schema_name, n.table_name].filter(Boolean).join('.'));
    for (const k of Object.keys(n)) walk(n[k]);
  })(j);
  log('guard_base_tables', names.join(','));
  log('guard_ok', j.error === false);

  // 9) materialize vs federated repeated scan
  a = t0(); await c.run(`CREATE TABLE snap AS SELECT * FROM pg.public.orders`); log('ctas_ms', ms(a, t0()).toFixed(0));
  a = t0(); await c.run(`SELECT count(*), sum(amount) FROM pg.public.orders`); log('federated_scan_ms', ms(a, t0()).toFixed(0));
  a = t0(); await c.run(`SELECT count(*), sum(amount) FROM snap`); log('local_scan_ms', ms(a, t0()).toFixed(0));

  // 10) snapshot consistency: two PG transactions? (single attach -> export snapshot)
  const q6 = await c.runAndReadAll(`SELECT count(*) FROM pg.public.orders`);
  log('pg_stat_rows', q6.getRows());

  fs.writeFileSync('/tmp/poc12/out.json', JSON.stringify({ done: true }));
})().catch(e => { console.error('FAIL', e); process.exit(1); });
