const { DuckDBInstance } = require('@duckdb/node-api');
const fs = require('fs');
const J = (x) => JSON.stringify(x, (_, v) => typeof v === 'bigint' ? v.toString() : v);
const lit = s => "'" + s.replaceAll("'","''") + "'";
const SENT = /"query_location":\d{19,}/g;
const parseAst = (s) => JSON.parse(s.replace(SENT, '"query_location":0'));
const findAll = (n, cls, out=[]) => { if(!n||typeof n!=='object') return out; if(n.class===cls) out.push(n); for(const k of Object.keys(n)) findAll(n[k], cls, out); return out; };

(async () => {
  const inst = await DuckDBInstance.create(':memory:'); const db = await inst.connect();
  const q = async (sql) => { try { return { ok:true, rows:(await db.runAndReadAll(sql)).getRows() } } catch(e){ return { ok:false, err:String(e.message).slice(0,90) } } };
  const ast = async (sql) => { const r = await q(`SELECT json_serialize_sql(${lit(sql)})`); return r.ok ? parseAst(r.rows[0][0]) : null; };
  const de = async (tree) => await q(`SELECT json_deserialize_sql(${lit(JSON.stringify(tree))})`);
  const out = { castTypeIds: {}, rewrite: {} };

  // 1) 枚举 cast_type.id 的真实语义
  const tmpl = await ast(`SELECT CAST(x AS TIMESTAMP) FROM t`);
  const base = findAll(tmpl, 'CAST')[0];
  for (const id of ['TIMESTAMP','TIMESTAMP_TZ','TIMESTAMP_S','TIMESTAMP_MS','TIMESTAMP_NS','TIME','DATE','VARCHAR']) {
    const t = JSON.parse(JSON.stringify(tmpl));
    findAll(t, 'CAST')[0].cast_type = { id, type_info: null };
    const r = await de(t);
    out.castTypeIds[id] = r.ok ? r.rows[0][0] : 'ERR:' + r.err;
  }

  // 2) 改写闭环：strftime(TIMESTAMPTZ const, fmt) -> strftime(CAST(const AS <id>), fmt)
  const src = `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+08', '%Y-%m-%d') AS v`;
  const tmplTs = findAll(await ast(`SELECT CAST(x AS TIMESTAMP) FROM t`), 'CAST')[0];
  const tree = await ast(src);
  const fn = (function f(n){ if(!n||typeof n!=='object') return null; if(n.class==='FUNCTION'&&n.function_name==='strftime') return n; for(const k of Object.keys(n)){ const r=f(n[k]); if(r) return r; } return null; })(tree);
  const c = JSON.parse(JSON.stringify(tmplTs)); c.alias=''; c.child = fn.children[0]; c.cast_type = { id:'TIMESTAMP', type_info:null }; c.try_cast=false;
  fn.children[0] = c;
  const r = await de(tree);
  out.rewrite.sql = r.ok ? r.rows[0][0] : 'ERR:' + r.err;
  if (r.ok) {
    await q(`SET TimeZone='UTC'`);
    const run = await q(r.rows[0][0]);
    const orig = await q(src);
    out.rewrite.exec = run.ok ? J(run.rows) : 'ERR:' + run.err;
    out.rewrite.orig = orig.ok ? J(orig.rows) : 'ERR:' + orig.err;
    out.rewrite.same = run.ok && orig.ok && J(run.rows) === J(orig.rows);
  }
  fs.writeFileSync('/tmp/poc26_final.json', JSON.stringify(out,null,1));
  console.log(J(out));
})().catch(e=>console.error('FATAL',e.message));
