const { DuckDBInstance } = require('@duckdb/node-api');
const path = '/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';
const { createDuckDB, NODE_RUNTIME, ConsoleLogger } = require(path + '/duckdb-node-blocking.cjs');
(async () => {
  const inst = await DuckDBInstance.create(':memory:'); const n = await inst.connect();
  const nq = (s) => { try { const t = n.runAndReadAll && null; return null } catch(e){} };
  const nodeQ = async (s) => { try { const r = await n.runAndReadAll(s); return { ok:true, v:String(r.getRows()[0]?.[0]?.valueOf?.() ?? r.getRows()[0]?.[0] ?? '') } } catch(e){ return { ok:false, err:e.message.slice(0,70) } } };
  const db = await createDuckDB({ mvp:{mainModule:path+'/duckdb-mvp.wasm'}, eh:{mainModule:path+'/duckdb-eh.wasm'} }, new ConsoleLogger(), NODE_RUNTIME);
  await db.instantiate(); const w = db.connect();
  const wasmQ = (s) => {
    try { const t = w.query(s); const names = t.schema.fields.map(f=>f.name); const rows = t.toArray().map(r => { const v = r[names[0]]; return typeof v==='bigint'?v.toString():(v&&typeof v==='object'&&'value' in v?String(v.value):v); });
      return { ok:true, v: String(rows[0] ?? '') };
    } catch(e){ return { ok:false, err:e.message.slice(0,80) } }
  };
  const fmts = ['%Y','%m','%d','%H','%M','%S','%z','%Z','%j','%W','%V','%G','%u','%s','%f','%n','%%'];
  console.log('fmt | NODE | WASM');
  const diffs = [];
  for (const f of fmts) {
    const sql = `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+08', '${f}') v`;
    const a = await nodeQ(sql), b = wasmQ(sql);
    const same = (a.ok === b.ok) && (a.ok ? a.v === b.v : true);
    if (!same) diffs.push({ fmt:f, node:a, wasm:b });
    console.log(`${f.padEnd(4)} | ${a.ok ? a.v : 'ERR:'+a.err.slice(0,30)} | ${b.ok ? b.v : 'ERR:'+b.err.slice(0,40)}${same?'':'   <<< DIFF'}`);
  }
  console.log('\nDIFFS:', JSON.stringify(diffs, null, 1));
  // 组合格式
  for (const f of ['%Y-%m-%dT%H:%M:%S%z','%Y-%m-%d %H:%M:%S']) {
    const sql = `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+08', '${f}') v`;
    console.log(`COMBO ${f} => node=${JSON.stringify(await nodeQ(sql))} wasm=${JSON.stringify(wasmQ(sql))}`);
  }
})().catch(e=>console.error('FATAL',e.message));
