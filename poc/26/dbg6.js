const path = '/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';
const { createDuckDB, NODE_RUNTIME, ConsoleLogger } = require(path + '/duckdb-node-blocking.cjs');
(async () => {
  const db = await createDuckDB({ mvp:{mainModule:path+'/duckdb-mvp.wasm'}, eh:{mainModule:path+'/duckdb-eh.wasm'} }, new ConsoleLogger(), NODE_RUNTIME);
  await db.instantiate(); const w = db.connect();
  const wq = (s) => {
    try {
      const t = w.query(s);
      const names = t.schema.fields.map(f => f.name);
      const rows = t.toArray().map(r => Object.fromEntries(names.map(n => [n, (() => { const v = r[n]; return typeof v === 'bigint' ? v.toString() : (v && typeof v === 'object' && 'value' in v ? String(v.value) : v); })()])));
      return { ok:true, rows };
    } catch(e){ return { ok:false, err:String(e.message).slice(0,100) }; }
  };
  const tests = [
    `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+00', '%Y-%m') v`,
    `SELECT strftime(CAST('2026-01-01 00:00:00+00' AS TIMESTAMP), '%Y-%m') v`,
    `SELECT strftime(TIMESTAMP '2026-01-01 00:00:00', '%Y-%m') v`,
  ];
  for (const t of tests) console.log(t.slice(0,66), '=>', JSON.stringify(wq(t)));
  wq(`CREATE TABLE IF NOT EXISTS tt(ts TIMESTAMPTZ)`); wq(`DELETE FROM tt`); wq(`INSERT INTO tt VALUES (TIMESTAMPTZ '2026-01-01 00:00:00+00')`);
  console.log('col-raw  =>', JSON.stringify(wq(`SELECT strftime(ts, '%Y-%m') v FROM tt`)));
  console.log('col-cast =>', JSON.stringify(wq(`SELECT strftime(CAST(ts AS TIMESTAMP), '%Y-%m') v FROM tt`)));
  const ser = wq(`SELECT json_serialize_sql('SELECT 1 AS a') v`);
  console.log('serialize =>', JSON.stringify(ser).slice(0,200));
  if (ser.ok) {
    const lit = "'" + String(ser.rows[0].v).replaceAll("'","''") + "'";
    console.log('deserialize =>', JSON.stringify(wq(`SELECT json_deserialize_sql(${lit}) v`)).slice(0,200));
  }
})().catch(e=>console.error('FATAL',e.message));
