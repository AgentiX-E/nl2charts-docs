const { DuckDBInstance } = require('@duckdb/node-api');
const J = (x) => JSON.stringify(x, (_, v) => typeof v === 'bigint' ? v.toString() : v);
const stable = (rows) => J(rows.map(r => J(r)).sort());   // 多重集比较
const CASES = require('/tmp/poc26/cases.js');

(async () => {
  const inst = await DuckDBInstance.create(':memory:'); const c = await inst.connect();
  await c.run(`CREATE TABLE orders(order_id BIGINT, region VARCHAR, amount DECIMAL(12,2), status VARCHAR, region_id INT)`);
  await c.run(`INSERT INTO orders VALUES (1,'华东',10.5,'paid',1),(2,'华北',20.5,'paid',2),(3,'华东',5.0,'refunded',1)`);
  await c.run(`CREATE TABLE regions(region_id INT, region_name VARCHAR)`);
  await c.run(`INSERT INTO regions VALUES (1,'华东区'),(2,'华北区')`);
  const q = async (sql, params) => { try { const r = params ? await c.runAndReadAll(sql, params) : await c.runAndReadAll(sql); return { ok: true, rows: r.getRows() }; } catch (e) { return { ok: false, err: String(e.message).slice(0,90) }; } };
  const lit = s => "'" + s.replaceAll("'","''") + "'";

  const out = { cases: [], summary: {} };
  for (const [name, sql] of CASES) {
    const rec = { name };
    const ser = await q(`SELECT json_serialize_sql(${lit(sql)})`);
    if (!ser.ok) { rec.ser = 'FAIL'; out.cases.push(rec); continue; }
    const j = JSON.parse(ser.rows[0][0]);
    if (j.error) { rec.ser = 'PARSE_ERROR'; out.cases.push(rec); continue; }
    const de = await q(`SELECT json_deserialize_sql(${lit(ser.rows[0][0])})`);
    if (!de.ok) { rec.ser='ok'; rec.de='FAIL'; out.cases.push(rec); continue; }
    const sql2 = de.rows[0][0];
    const ser2 = await q(`SELECT json_serialize_sql(${lit(sql2)})`);
    const a2 = ser2.ok ? ser2.rows[0][0] : null;
    const strip = (s) => s ? s.replace(/"query_location":\d+,?/g, '') : s;
    rec.ser='ok'; rec.de='ok';
    rec.astIdempotent = a2 !== null && strip(a2) === strip(ser.rows[0][0]);
    rec.textIdentical = sql2.trim() === sql.trim();
    const isParam = /\?/.test(sql);
    const a = await q(sql, isParam ? [1] : undefined);
    const b = await q(sql2, isParam ? [1] : undefined);
    rec.sameMultiset = a.ok && b.ok ? stable(a.rows) === stable(b.rows) : false;
    rec.sameOrder = a.ok && b.ok ? J(a.rows) === J(b.rows) : false;
    if (a.ok !== b.ok) rec.execMismatch = `${a.ok}/${b.ok}`;
    out.cases.push(rec);
  }

  // 改写实验：strftime(TIMESTAMPTZ, fmt) -> strftime(CAST(x AS TIMESTAMP), fmt)，用正确 CAST schema
  const rw = { name: 'rewrite_strftime' };
  const src = `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+00', '%Y-%m') AS m`;
  const s0 = await q(`SELECT json_serialize_sql(${lit(src)})`);
  const tree = JSON.parse(s0.rows[0][0]);
  let hits = 0;
  const walk = (n, parent, key) => {
    if (!n || typeof n !== 'object') return;
    if (n.class === 'FUNCTION' && n.function_name === 'strftime' && Array.isArray(n.children) && n.children.length === 2) {
      n.children[0] = { class:'CAST', type:'OPERATOR_CAST', alias:'', child: n.children[0],
                        cast_type: { id:'TIMESTAMP', type_info: null }, try_cast: false };
      hits++;
    }
    for (const k of Object.keys(n)) walk(n[k], n, k);
  };
  walk(tree);
  rw.hits = hits;
  const de2 = await q(`SELECT json_deserialize_sql(${lit(JSON.stringify(tree))})`);
  if (de2.ok) {
    rw.sql = de2.rows[0][0];
    const run = await q(rw.sql);
    rw.ok = run.ok; rw.rows = run.ok ? J(run.rows) : run.err;
  } else rw.err = de2.err;
  out.rewrite = rw;

  const n = out.cases.length;
  out.summary = { total:n, serOk: out.cases.filter(x=>x.ser==='ok').length,
    deOk: out.cases.filter(x=>x.de==='ok').length,
    sameMultiset: out.cases.filter(x=>x.sameMultiset).length,
    sameOrder: out.cases.filter(x=>x.sameOrder).length,
    astIdempotent: out.cases.filter(x=>x.astIdempotent).length,
    textIdentical: out.cases.filter(x=>x.textIdentical).length };
  require('fs').writeFileSync('/tmp/poc26_results2.json', JSON.stringify(out,null,1));
  for (const r of out.cases) console.log(`[${r.name}] ser=${r.ser} de=${r.de||'-'} multiset=${r.sameMultiset} order=${r.sameOrder} astIdem=${r.astIdempotent} text=${r.textIdentical}`);
  console.log('REWRITE', J(rw));
  console.log('SUMMARY', J(out.summary));
})().catch(e => console.error('FATAL', e));
