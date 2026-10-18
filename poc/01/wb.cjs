const path = '/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';
const { createDuckDB, NODE_RUNTIME, ConsoleLogger } = require(path + '/duckdb-node-blocking.cjs');
(async () => {
  const db = await createDuckDB({ mvp: { mainModule: path + '/duckdb-mvp.wasm' }, eh: { mainModule: path + '/duckdb-eh.wasm' } }, new ConsoleLogger(), NODE_RUNTIME);
  await db.instantiate();
  const conn = db.connect();
  console.log(conn.query('SELECT version() v').toArray());
})().catch(e => console.error('ERR', e.message));
