const { DuckDBInstance } = require('@duckdb/node-api');
const path = '/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';
const { createDuckDB, NODE_RUNTIME, ConsoleLogger } = require(path + '/duckdb-node-blocking.cjs');
(async () => {
  const inst = await DuckDBInstance.create(':memory:'); const n = await inst.connect();
  const nq = async (s) => { try { return { ok:true, v:String((await n.runAndReadAll(s)).getRows()[0]?.[0]?.valueOf?.() ?? '') } } catch(e){ return { ok:false, err:e.message.slice(0,80) } } };
  const tests = [
    `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+00', '%Y-%m') v`,
    `SELECT strftime(CAST('2026-01-01 00:00:00+00' AS TIMESTAMP), '%Y-%m') v`,
    `SELECT strftime(CAST('2026-01-01 00:00:00+00' AS TIMESTAMPTZ), '%Y-%m') v`,
    `SELECT strftime(CAST('2026-01-01 00:00:00+00' AS TIMESTAMP WITH TIME ZONE), '%Y-%m') v`,
    `SELECT strftime(TIMESTAMP '2026-01-01 00:00:00', '%Y-%m') v`,
  ];
  console.log('--- NODE ---');
  for (const t of tests) console.log(t.slice(0,70), '=>', JSON.stringify(await nq(t)));

  const db = await createDuckDB({ mvp:{mainModule:path+'/duckdb-mvp.wasm'}, eh:{mainModule:path+'/duckdb-eh.wasm'} }, new ConsoleLogger(), NODE_RUNTIME);
  await db.instantiate(); const w = db.connect();
  const wq = (s) => { try { const t = w.query(s); return { ok:true, n:t.toArray().length, v:String(t.toArray()[0]?.[0] ?? '') }; } catch(e){ return { ok:false, err:e.message.slice(0,90) } } };
  console.log('--- WASM ---');
  for (const t of tests) console.log(t.slice(0,70), '=>', JSON.stringify(wq(t)));
  // 列形式的 TIMESTAMPTZ（POC-14 的场景）
  console.log('--- WASM 列形式 ---');
  console.log(JSON.stringify(wq(`CREATE TABLE tt(ts TIMESTAMPTZ)`)));
  console.log(JSON.stringify(wq(`INSERT INTO tt VALUES (TIMESTAMPTZ '2026-01-01 00:00:00+00')`)));
  console.log('col:', JSON.stringify(wq(`SELECT strftime(ts, '%Y-%m') v FROM tt`)));
  console.log('col-cast:', JSON.stringify(wq(`SELECT strftime(CAST(ts AS TIMESTAMP), '%Y-%m') v FROM tt`)));
  // json_deserialize_sql 在 WASM 上的真实可用性
  console.log('--- WASM json_deserialize ---');
  console.log('ser:', JSON.stringify(wq(`SELECT json_serialize_sql('SELECT 1')`)));
  const s = w.query(`SELECT json_serialize_sql('SELECT 1')`).toArray()[0][0];
  const lit = "'" + String(s).replaceAll("'","''") + "'";
  try { const r = w.query(`SELECT json_deserialize_sql(${lit})`); console.log('deser:', JSON.stringify({ ok:true, v:String(r.toArray()[0][0]).slice(0,60) })); } catch(e) { console.log('deser:', JSON.stringify({ ok:false, err:e.message.slice(0,90) })); }
})().catch(e=>console.error('FATAL',e.message));
