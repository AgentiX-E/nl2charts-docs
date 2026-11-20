const { DuckDBInstance } = require('@duckdb/node-api');
const path = '/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';
const { createDuckDB, NODE_RUNTIME, ConsoleLogger } = require(path + '/duckdb-node-blocking.cjs');
(async () => {
  const inst = await DuckDBInstance.create(':memory:'); const n = await inst.connect();
  const nodeQ = async (s) => { try { const r = await n.runAndReadAll(s); return { ok:true, v:String(r.getRows()[0]?.[0]?.valueOf?.() ?? r.getRows()[0]?.[0] ?? '') } } catch(e){ return { ok:false, err:e.message.slice(0,60) } } };
  const db = await createDuckDB({ mvp:{mainModule:path+'/duckdb-mvp.wasm'}, eh:{mainModule:path+'/duckdb-eh.wasm'} }, new ConsoleLogger(), NODE_RUNTIME);
  await db.instantiate(); const w = db.connect();
  const wasmQ = (s) => { try { const t = w.query(s); const k = t.schema.fields[0].name; const rows = t.toArray().map(r => { const v = r[k]; return typeof v==='bigint'?v.toString():(v&&typeof v==='object'&&'value' in v?String(v.value):v); }); return { ok:true, v:String(rows[0]??'') } } catch(e){ return { ok:false, err:e.message.slice(0,60) } } };

  console.log('--- 默认时区 ---');
  console.log('node TimeZone :', JSON.stringify(await nodeQ(`SELECT current_setting('TimeZone') v`)));
  console.log('wasm TimeZone :', JSON.stringify(wasmQ(`SELECT current_setting('TimeZone') v`)));
  console.log('node now()    :', JSON.stringify(await nodeQ(`SELECT strftime(now(), '%Y-%m-%dT%H:%M:%S%z') v`)));
  console.log('wasm now()    :', JSON.stringify(wasmQ(`SELECT strftime(now(), '%Y-%m-%dT%H:%M:%S%z') v`)));

  console.log('\n--- 显式 SET TimeZone = UTC 后 ---');
  await nodeQ(`SET TimeZone='UTC'`); wasmQ(`SET TimeZone='UTC'`);
  const sql = `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+08', '%Y-%m-%dT%H:%M:%S%z|%W|%u|%j') v`;
  console.log('node:', JSON.stringify(await nodeQ(sql)));
  console.log('wasm:', JSON.stringify(wasmQ(sql)));

  console.log('\n--- 显式 SET TimeZone = Asia/Shanghai 后（WASM 是否支持命名时区） ---');
  console.log('wasm SET sh:', JSON.stringify(wasmQ(`SET TimeZone='Asia/Shanghai'`)));
  console.log('wasm sh val:', JSON.stringify(wasmQ(`SELECT current_setting('TimeZone') v`)));
  console.log('wasm sh sql:', JSON.stringify(wasmQ(sql)));
})().catch(e=>console.error('FATAL',e.message));
