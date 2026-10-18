const { DuckDBInstance } = require('@duckdb/node-api');
const Q = (p) => ([
 ["Q1_revenue_region", `SELECT r.region_name, sum(o.amount) v FROM ${p}.orders2 o JOIN ${p}.regions2 r USING(region_id) WHERE o.status='paid' GROUP BY 1 ORDER BY 1`],
 ["Q2_revenue_category", `SELECT p.category, sum(oi.qty*oi.unit_price) v FROM ${p}.order_items2 oi JOIN ${p}.orders2 o USING(order_id) JOIN ${p}.products2 p USING(product_id) WHERE o.status='paid' GROUP BY 1 ORDER BY 1`],
 ["Q3_aov_region", `SELECT r.region_name, sum(o.amount)/count(DISTINCT o.order_id) v FROM ${p}.orders2 o JOIN ${p}.regions2 r USING(region_id) WHERE o.status='paid' GROUP BY 1 ORDER BY 1`],
 ["Q4_cum", `SELECT m, sum(v) OVER (ORDER BY m) v FROM (SELECT strftime(created_at,'%Y-%m') m, sum(amount) v FROM ${p}.orders2 WHERE status='paid' GROUP BY 1) t ORDER BY 1`],
 ["Q5_conversion", `SELECT r.region_name, count(DISTINCT CASE WHEN o.status='paid' THEN o.order_id END)*1.0/count(DISTINCT o.order_id) v FROM ${p}.orders2 o JOIN ${p}.regions2 r USING(region_id) GROUP BY 1 ORDER BY 1`],
 ["Q6_inv_eom", `SELECT sum(qty) v FROM (SELECT product_id, qty, row_number() OVER (PARTITION BY product_id, date_trunc('month', snapshot_date) ORDER BY snapshot_date DESC) rn FROM ${p}.inventory2) WHERE rn=1`],
 ["Q7_multi", `WITH b AS (SELECT r.region_name, sum(o.amount) rev, count(DISTINCT o.order_id) oc FROM ${p}.orders2 o JOIN ${p}.regions2 r USING(region_id) WHERE o.status='paid' GROUP BY 1) SELECT region_name, rev, rev/oc aov FROM b ORDER BY 1`],
]);
const J = (x) => JSON.stringify(x, (_, v) => typeof v === 'bigint' ? v.toString() : (typeof v === 'number' ? Math.round(v*1e6)/1e6 : v));
(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const c = await inst.connect();
  await c.run('INSTALL postgres'); await c.run('LOAD postgres');
  await c.run(`ATTACH 'host=127.0.0.1 port=5432 dbname=analytics user=t2c password=t2cpass' AS src (TYPE postgres, READ_ONLY, SCHEMA 'public')`);
  await c.run(`ATTACH ':memory:' AS mat`);
  for (const t of ['orders2','order_items2','products2','regions2','inventory2'])
    await c.run(`CREATE TABLE mat.${t} AS SELECT * FROM src.${t}`);
  let pass = 0;
  for (const [name, sql] of Q('src')) {
    const a = await c.runAndReadAll(sql);
    const b = await c.runAndReadAll(sql.replaceAll('src.', 'mat.'));
    const same = J(a.getRows()) === J(b.getRows());
    pass += same;
    console.log(`[${name}] federated==materialized: ${same}${same ? '' : '\n  fed=' + J(a.getRows()).slice(0,200) + '\n  mat=' + J(b.getRows()).slice(0,200)}`);
  }
  console.log(`PASS ${pass}/7`);
})().catch(e => { console.error('FAIL', e); process.exit(1); });
