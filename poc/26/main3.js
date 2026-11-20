const { DuckDBInstance } = require('@duckdb/node-api');
const fs = require('fs');
const J = (x) => JSON.stringify(x, (_, v) => typeof v === 'bigint' ? v.toString() : v);
const lit = s => "'" + s.replaceAll("'","''") + "'";

(async () => {
  const inst = await DuckDBInstance.create(':memory:'); const c = await inst.connect();
  const q = async (sql) => { try { return { ok:true, rows:(await c.runAndReadAll(sql)).getRows() }; } catch(e){ return { ok:false, err:String(e.message).slice(0,90) }; } };
  const rewrite = async (src, fnName, makeNode) => {
    const s0 = await q(`SELECT json_serialize_sql(${lit(src)})`);
    const tree = JSON.parse(s0.rows[0][0]);
    let hits = 0;
    const walk = (n) => { if(!n||typeof n!=='object')return;
      if (n.class==='FUNCTION' && n.function_name===fnName && Array.isArray(n.children)) { hits += makeNode(n); }
      for (const k of Object.keys(n)) walk(n[k]); };
    walk(tree);
    const de = await q(`SELECT json_deserialize_sql(${lit(JSON.stringify(tree))})`);
    return { hits, sql: de.ok ? de.rows[0][0] : null, err: de.ok ? null : de.err };
  };
  const castNode = (child, typeId, loc) => ({ class:'CAST', type:'OPERATOR_CAST', alias:'',
      query_location: loc ?? 0, child, cast_type:{ id:typeId, type_info:null }, try_cast:false });

  // R1: strftime(TIMESTAMPTZ, fmt) -> strftime(CAST(x AS TIMESTAMP), fmt)
  const r1 = await rewrite(`SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+00', '%Y-%m') AS m`, 'strftime',
    (n) => { if (n.children.length!==2) return 0; n.children[0] = castNode(n.children[0], 'TIMESTAMP', n.query_location); return 1; });
  // R2: date_trunc('month', TIMESTAMPTZ) -> date_trunc('month', CAST(... AS TIMESTAMP))
  const r2 = await rewrite(`SELECT date_trunc('month', TIMESTAMPTZ '2026-03-15 00:00:00+00') AS d`, 'date_trunc',
    (n) => { if (n.children.length!==2) return 0; n.children[1] = castNode(n.children[1], 'TIMESTAMP', n.query_location); return 1; });
  const out = { r1: { ...r1 }, r2: { ...r2 } };
  for (const k of ['r1','r2']) {
    if (out[k].sql) { const run = await q(out[k].sql); out[k].exec = run.ok ? J(run.rows) : 'ERR:'+run.err; }
  }
  fs.writeFileSync('/tmp/poc26_rewrite.json', JSON.stringify(out,null,1));
  console.log(J(out));
})().catch(e => console.error('FATAL', e.message));
