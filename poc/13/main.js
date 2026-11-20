const { DuckDBInstance } = require('@duckdb/node-api');

const ms = (a, b) => Number(b - a) / 1e6;
const J = (x) => JSON.stringify(x, (_, v) => typeof v === 'bigint' ? v.toString() : v);

const QUERIES = [
  ['agg_by_status', `SELECT status, count(*) n, sum(amount) amt FROM src.orders GROUP BY 1 ORDER BY 1`],
  ['tz_bucket', `SELECT date_trunc('month', created_at) m, count(*) n FROM src.orders GROUP BY 1 ORDER BY 1`],
  ['jsonb_field', `SELECT payload->>'channel' ch, count(*) n FROM src.orders GROUP BY 1 ORDER BY 1`],
  ['uuid_distinct', `SELECT count(DISTINCT uid) n FROM src.orders`],
  ['array_len', `SELECT sum(len(tags)) n FROM src.orders`],
  ['numeric_round', `SELECT round(avg(amount), 4) a FROM src.orders`],
  ['window', `SELECT order_id, row_number() OVER (PARTITION BY status ORDER BY amount DESC) rn FROM src.orders WHERE order_id <= 50 ORDER BY order_id`],
  ['join_dim', `SELECT d.country, count(*) n FROM src.orders o JOIN src.dim_region d USING(region_id) GROUP BY 1 ORDER BY 1`],
  ['nulls', `SELECT count(*) FILTER (WHERE payload IS NULL) a, count(*) FILTER (WHERE uid IS NULL) b FROM src.orders`],
  ['string_agg', `SELECT status, string_agg(DISTINCT payload->>'channel', ',' ORDER BY payload->>'channel') s FROM src.orders WHERE order_id <= 200 GROUP BY 1 ORDER BY 1`],
];

(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const c = await inst.connect();
  await c.run('INSTALL postgres'); await c.run('LOAD postgres');
  await c.run(`ATTACH 'host=127.0.0.1 port=5432 dbname=analytics user=t2c password=t2cpass' AS src (TYPE postgres, READ_ONLY, SCHEMA 'public')`);

  // materialize a snapshot under catalog "mat" (same names so SQL text is identical except catalog)
  await c.run(`ATTACH ':memory:' AS mat`);
  await c.run(`CREATE TABLE mat.orders AS SELECT * FROM src.orders`);
  await c.run(`CREATE TABLE mat.dim_region AS SELECT * FROM src.dim_region`);

  const res = [];
  for (const [name, sql] of QUERIES) {
    const qf = sql.replaceAll('src.', 'src.');
    const qm = sql.replaceAll('src.', 'mat.');
    let a, b, ea = null, eb = null, ta, tb;
    try { ta = process.hrtime.bigint(); a = await c.runAndReadAll(qf); ta = ms(ta, process.hrtime.bigint()); } catch (e) { ea = e.message.slice(0, 100); }
    try { tb = process.hrtime.bigint(); b = await c.runAndReadAll(qm); tb = ms(tb, process.hrtime.bigint()); } catch (e) { eb = e.message.slice(0, 100); }
    let same = false, diffs = [];
    if (!ea && !eb) {
      const ra = a.getRows(), rb = b.getRows();
      same = J(ra) === J(rb);
      if (!same) {
        for (let i = 0; i < Math.max(ra.length, rb.length) && diffs.length < 2; i++) {
          if (J(ra[i]) !== J(rb[i])) diffs.push({ i, fed: J(ra[i]), mat: J(rb[i]) });
        }
      }
    }
    res.push({ name, same, fedMs: ta && +ta.toFixed(1), matMs: tb && +tb.toFixed(1), ea, eb, diffs,
               fedTypes: a ? a.columnTypes().map(String) : null, matTypes: b ? b.columnTypes().map(String) : null });
    console.log(`[${name}] same=${same} fed=${ta?.toFixed(1)}ms mat=${tb?.toFixed(1)}ms ${ea ? 'FEDERR:' + ea : ''} ${eb ? 'MATERR:' + eb : ''}`);
    if (diffs.length) console.log('   diff:', J(diffs));
  }

  // ---- guard adversarial checks on catalog-qualified SQL ----
  const GUARD_CASES = [
    ['allow_select', `SELECT region_name FROM src.dim_region WHERE region_id = 1`],
    ['deny_copy_out', `COPY (SELECT * FROM src.orders) TO '/tmp/leak.csv'`],
    ['deny_install', `INSTALL httpfs`],
    ['deny_attach', `ATTACH 'x.db' AS y`],
    ['deny_settings', `SELECT * FROM duckdb_settings()`],
    ['deny_pg_catalog', `SELECT * FROM src.pg_catalog.pg_user`],
    ['deny_info_schema', `SELECT * FROM src.information_schema.tables`],
    ['deny_pivot', `PIVOT src.orders ON status USING count(*)`],
    ['deny_union_catalog', `SELECT 1 UNION ALL SELECT count(*) FROM src.orders`],
    ['deny_alias_shadow', `SELECT src.x FROM src.orders src`],
  ];
  const guard = [];
  for (const [name, sql] of GUARD_CASES) {
    const lit = "'" + sql.replaceAll("'", "''") + "'";
    let r;
    try { r = await c.runAndReadAll(`SELECT json_serialize_sql(${lit})`); }
    catch (e) { guard.push({ name, parsed: false, error: String(e.message).slice(0, 90) }); console.log(`[guard:${name}] PARSE-FAIL ${String(e.message).slice(0,90)}`); continue; }
    const j = JSON.parse(r.getRows()[0][0]);
    const nodes = new Set(), tables = [];
    (function walk(n) {
      if (!n || typeof n !== 'object') return;
      if (n.type) nodes.add(n.type);
      if (n.type === 'BASE_TABLE') tables.push([n.catalog_name, n.schema_name, n.table_name].join('.'));
      for (const k of Object.keys(n)) walk(n[k]);
    })(j);
    guard.push({ name, parsed: j.error === false, error: j.errorMessage || null,
                 stmtType: j.statements?.[0]?.node?.type, tables,
                 hasCopy: [...nodes].some(t => String(t).includes('COPY')),
                 hasAttach: [...nodes].some(t => String(t).includes('ATTACH') || String(t).includes('INSTALL')) });
    console.log(`[guard:${name}] parsed=${j.error === false} stmt=${j.statements?.[0]?.node?.type} tables=${tables.join(',')}`);
  }

  require('fs').writeFileSync('/tmp/poc13_results.json', J({ res, guard }));
})().catch(e => { console.error('FAIL', e); process.exit(1); });
