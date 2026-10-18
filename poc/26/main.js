const { DuckDBInstance } = require('@duckdb/node-api');

const J = (x) => JSON.stringify(x, (_, v) => typeof v === 'bigint' ? v.toString() : v);

// 20 条覆盖性查询：从简单到复杂，重点覆盖"改写层必须保住"的东西
const CASES = [
  ['simple', `SELECT 1 AS a`],
  ['where', `SELECT region, sum(amount) AS s FROM orders WHERE status='paid' GROUP BY 1 ORDER BY 2 DESC`],
  ['cte', `WITH a AS (SELECT 1 x), b AS (SELECT x+1 y FROM a) SELECT * FROM b`],
  ['window', `SELECT order_id, row_number() OVER (PARTITION BY region ORDER BY amount DESC) rn FROM orders`],
  ['lambda', `SELECT list_transform([1,2,3], x -> x + 1) AS l`],
  ['lambda_colon', `SELECT list_filter([1,2,3], x : x > 1) AS l`],
  ['decimal_literal', `SELECT 1.2345678901234567890123::DECIMAL(38,22) AS d`],
  ['chinese_ident', `SELECT 1 AS "金额", '中文' AS "地区"`],
  ['cast_nested', `SELECT CAST(CAST('2026-01-01' AS DATE) AS TIMESTAMP) AS t`],
  ['join_alias', `SELECT o.order_id, r.region_name FROM orders o LEFT JOIN regions r ON o.region_id = r.region_id`],
  ['union', `SELECT 1 a UNION ALL SELECT 2`],
  ['subquery_from', `SELECT * FROM (SELECT 1 a) t WHERE t.a > 0`],
  ['string_escape', `SELECT 'it''s a "test"' AS s`],
  ['interval', `SELECT DATE '2026-01-01' + INTERVAL 1 MONTH AS d`],
  ['case_when', `SELECT CASE WHEN 1=1 THEN 'a' ELSE 'b' END AS c`],
  ['qualify', `SELECT 1 x QUALIFY row_number() OVER () = 1`],
  ['grouping_sets', `SELECT region, status, count(*) c FROM orders GROUP BY GROUPING SETS ((region),(status),())`],
  ['filter_agg', `SELECT count(*) FILTER (WHERE amount > 10) c FROM orders`],
  ['struct', `SELECT {'a': 1, 'b': 'x'} AS s`],
  ['params_like', `SELECT ?::INT AS p`],
];

(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const c = await inst.connect();
  await c.run(`CREATE TABLE orders(order_id BIGINT, region VARCHAR, amount DECIMAL(12,2), status VARCHAR, region_id INT)`);
  await c.run(`INSERT INTO orders VALUES (1,'华东',10.5,'paid',1),(2,'华北',20.5,'paid',2),(3,'华东',5.0,'refunded',1)`);
  await c.run(`CREATE TABLE regions(region_id INT, region_name VARCHAR)`);
  await c.run(`INSERT INTO regions VALUES (1,'华东区'),(2,'华北区')`);

  const q = async (sql, params) => {
    try { const r = params ? await c.runAndReadAll(sql, params) : await c.runAndReadAll(sql); return { ok: true, rows: r.getRows() }; }
    catch (e) { return { ok: false, err: String(e.message).slice(0, 90) }; }
  };
  const lit = (s) => "'" + s.replaceAll("'", "''") + "'";

  const out = { version: null, cases: [], summary: {} };
  out.version = (await q('SELECT version()')).rows[0][0];

  for (const [name, sql] of CASES) {
    const rec = { name, sql };
    // 1) serialize
    let ast = null;
    const ser = await q(`SELECT json_serialize_sql(${lit(sql)})`);
    if (!ser.ok) { rec.serialize = 'FAIL:' + ser.err; out.cases.push(rec); continue; }
    const j = JSON.parse(ser.rows[0][0]);
    if (j.error) { rec.serialize = 'ERROR:' + String(j.error).slice(0, 60) + ' msg=' + String(j.error_message || '').slice(0, 60); out.cases.push(rec); continue; }
    ast = ser.rows[0][0];
    rec.serialize = 'ok';
    rec.astBytes = ast.length;

    // 2) deserialize
    const de = await q(`SELECT json_deserialize_sql(${lit(ast)})`);
    if (!de.ok) { rec.deserialize = 'FAIL:' + de.err; out.cases.push(rec); continue; }
    const sql2 = de.rows[0][0];
    rec.deserialize = 'ok';
    rec.sql2 = sql2;
    rec.identicalText = sql2.trim() === sql.trim();

    // 3) 二次 serialize 是否稳定（幂等）
    const ser2 = await q(`SELECT json_serialize_sql(${lit(sql2)})`);
    rec.astStable = ser2.ok && ser2.rows[0][0] === ast;

    // 4) 语义：两侧执行结果是否一致
    const isParam = /\?/.test(sql);
    const a = await q(sql, isParam ? [1] : undefined);
    const b = await q(sql2, isParam ? [1] : undefined);
    rec.execA = a.ok ? 'ok' : 'ERR';
    rec.execB = b.ok ? 'ok' : 'ERR';
    rec.sameResult = a.ok && b.ok ? J(a.rows) === J(b.rows) : (a.ok === b.ok && String(a.err) === String(b.err));
    rec.rowsA = a.ok ? a.rows.length : null;
    out.cases.push(rec);
  }

  // 5) 改写实验：把 strftime(TIMESTAMPTZ,..) 改成 CAST 后再 strftime（CDS 降级的真实用法）
  const rw = { name: 'rewrite_strftime', ok: false };
  const src = `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+00', '%Y-%m') AS m`;
  const s0 = await q(`SELECT json_serialize_sql(${lit(src)})`);
  if (s0.ok) {
    const tree = JSON.parse(s0.rows[0][0]);
    let hits = 0;
    const walk = (n) => {
      if (!n || typeof n !== 'object') return;
      if (n.class === 'FUNCTION' && n.function_name === 'strftime') {
        // 目标：strftime(CAST(arg0 AS TIMESTAMP), fmt)
        const args = n.children || [];
        if (args.length === 2) {
          args[0] = { class: 'CAST', children: [args[0]], cast_type: { id: 'TIMESTAMP' } };
          hits++;
        }
      }
      for (const k of Object.keys(n)) walk(n[k]);
    };
    walk(tree);
    rw.hits = hits;
    const de2 = await q(`SELECT json_deserialize_sql(${lit(JSON.stringify(tree))})`);
    if (de2.ok) {
      rw.rewritten = de2.rows[0][0];
      const run = await q(rw.rewritten);
      rw.exec = run.ok ? 'ok ' + J(run.rows) : 'ERR ' + run.err;
      rw.ok = run.ok;
    } else rw.error = de2.err;
  }
  out.rewrite = rw;

  // summary
  const n = out.cases.length;
  out.summary = {
    total: n,
    serializeOk: out.cases.filter(x => x.serialize === 'ok').length,
    deserializeOk: out.cases.filter(x => x.deserialize === 'ok').length,
    identicalText: out.cases.filter(x => x.identicalText).length,
    astStable: out.cases.filter(x => x.astStable).length,
    sameResult: out.cases.filter(x => x.sameResult).length,
  };
  require('fs').writeFileSync('/tmp/poc26_results.json', JSON.stringify(out, null, 1));
  console.log('VERSION', out.version);
  for (const r of out.cases) {
    console.log(`[${r.name}] ser=${r.serialize} de=${r.deserialize || '-'} same=${r.sameResult === undefined ? '-' : r.sameResult} text=${r.identicalText === undefined ? '-' : r.identicalText} astStable=${r.astStable === undefined ? '-' : r.astStable}`);
  }
  console.log('REWRITE', J(rw));
  console.log('SUMMARY', J(out.summary));
})().catch(e => { console.error('FATAL', e); process.exit(1); });
