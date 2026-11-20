const { DuckDBInstance } = require('@duckdb/node-api');
const fs = require('fs');
const path = '/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';
const { createDuckDB, NODE_RUNTIME, ConsoleLogger } = require(path + '/duckdb-node-blocking.cjs');
const J = (x) => JSON.stringify(x, (_, v) => typeof v === 'bigint' ? v.toString() : v);
const lit = s => "'" + s.replaceAll("'","''") + "'";

// ★ 关键修复：进入 JS 前把 uint64 哨兵规范化为 0
const SENTINEL = /"query_location":\d{19,}/g;
const parseAst = (s) => JSON.parse(s.replace(SENTINEL, '"query_location":0'));
const findClass = (n, cls, out=[]) => { if(!n||typeof n!=='object') return out; if(n.class===cls) out.push(n); for(const k of Object.keys(n)) findClass(n[k], cls, out); return out; };
const findFn = (n, name, out=[]) => { if(!n||typeof n!=='object') return out; if(n.class==='FUNCTION' && n.function_name===name) out.push(n); for(const k of Object.keys(n)) findFn(n[k], name, out); return out; };

(async () => {
  const out = {};

  // ---------- Node 侧 ----------
  const inst = await DuckDBInstance.create(':memory:'); const n = await inst.connect();
  const nq = async (sql) => { try { return { ok:true, rows:(await n.runAndReadAll(sql)).getRows() }; } catch(e){ return { ok:false, err:String(e.message).slice(0,100) }; } };
  const ser = async (sql) => { const r = await nq(`SELECT json_serialize_sql(${lit(sql)})`); return r.ok ? JSON.parse(r.rows[0][0]) : null; };
  const de = async (tree) => nq(`SELECT json_deserialize_sql(${lit(JSON.stringify(tree))})`);

  out.env = { nodeVersion: (await nq('SELECT version()')).rows[0][0] };

  // 1) 哨兵陷阱复现
  const src = `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+00', '%Y-%m') AS m`;
  const astStr = (await nq(`SELECT json_serialize_sql(${lit(src)})`)).rows[0][0];
  out.sentinel = {
    naiveRoundtrip: (await nq(`SELECT json_deserialize_sql(${lit(JSON.stringify(JSON.parse(astStr)))})`)).ok === false,
    fixedRoundtrip: (await nq(`SELECT json_deserialize_sql(${lit(JSON.stringify(parseAst(astStr)))})`)).ok === true,
    valueInAst: (astStr.match(/"query_location":(\d{19,})/) || [])[1],
    valueAfterJsParse: String(JSON.parse(astStr).statements ? 0 : 0) // 占位
  };
  // 精确展示精度损失
  const raw = (astStr.match(/"query_location":(\d{19,})/) || [])[1];
  out.sentinel.precisionLoss = { raw, viaJs: JSON.stringify(Number(raw)) };

  // 2) 改写：strftime(TIMESTAMPTZ, fmt) -> strftime(CAST(x AS TIMESTAMP), fmt)
  const tree = parseAst(astStr);
  const fns = findFn(tree, 'strftime');
  const tmplCast = findClass(parseAst((await nq(`SELECT json_serialize_sql(${lit('SELECT CAST(a AS TIMESTAMP) FROM t')})`)).rows[0][0]), 'CAST')[0];
  for (const f of fns) {
    if (!Array.isArray(f.children) || f.children.length !== 2) continue;
    if (f.children[0].class !== 'CONSTANT') continue;
    const c = JSON.parse(JSON.stringify(tmplCast));
    c.alias = ''; c.child = f.children[0]; c.cast_type = { id: 'TIMESTAMP', type_info: null }; c.try_cast = false;
    f.children[0] = c;
  }
  const rw = await de(tree);
  out.rewrite = { nodeDeOk: rw.ok, sql: rw.ok ? rw.rows[0][0] : null, err: rw.err };
  if (rw.ok) { const r = await nq(rw.sql); out.rewrite.nodeExec = r.ok ? J(r.rows) : 'ERR:' + r.err; }

  // ---------- WASM 侧 ----------
  const db = await createDuckDB({ mvp:{ mainModule: path + '/duckdb-mvp.wasm' }, eh:{ mainModule: path + '/duckdb-eh.wasm' } }, new ConsoleLogger(), NODE_RUNTIME).catch(e => { out.wasm = { init: 'FAIL:' + e.message.slice(0,80) }; return null; }) || null;
  if (db) { try { await db.instantiate(); } catch (e) { out.wasm = { init: 'FAIL:' + e.message.slice(0,80) }; } }
  if (db && !out.wasm) {
    const w = db.connect();
    const wq = (sql) => { try { return { ok:true, rows:w.query(sql).toArray() } } catch(e){ return { ok:false, err:String(e.message).slice(0,110) } } };
    const ver = wq('SELECT version() v');
    out.wasm = { version: ver.ok ? String(ver.rows[0].v ?? ver.rows[0][0]?.valueOf?.() ?? '') : null };
    out.wasm.originalOnWasm = wq(src);
    out.wasm.rewrittenOnWasm = rw.ok ? wq(rw.sql) : null;
    out.wasm.hasDeserialize = (() => { try { const r = w.query(`SELECT json_deserialize_sql('{"error":false,"statements":[]}')`); return { ok:true, v:String(r.toArray()[0][0]).slice(0,60) }; } catch(e){ return { ok:false, err:String(e.message).slice(0,80) }; } })();
    out.wasm.originalOnWasm = out.wasm.originalOnWasm.ok ? { ok:true, rows: out.wasm.originalOnWasm.rows.length } : out.wasm.originalOnWasm;
    if (out.wasm.rewrittenOnWasm) out.wasm.rewrittenOnWasm = out.wasm.rewrittenOnWasm.ok ? { ok:true, rows: out.wasm.rewrittenOnWasm.rows.length, val: String(out.wasm.rewrittenOnWasm.rows[0]?.[0]?.valueOf?.() ?? '') } : out.wasm.rewrittenOnWasm;
  }

  fs.writeFileSync('/tmp/poc26_results4.json', JSON.stringify(out,null,1));
  console.log(J(out));
})().catch(e => console.error('FATAL', e.message));
