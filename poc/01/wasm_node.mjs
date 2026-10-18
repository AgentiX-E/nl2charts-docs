import * as duckdb from '@duckdb/duckdb-wasm';
import path from 'node:path';

import Worker from 'web-worker';


const dist = '/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';

const MANUAL = {
  mvp: { mainModule: `${dist}/duckdb-mvp.wasm`, mainWorker: `${dist}/duckdb-node-mvp.worker.cjs` },
  eh:  { mainModule: `${dist}/duckdb-eh.wasm`,  mainWorker: `${dist}/duckdb-node-eh.worker.cjs` },
};
const bundle = await duckdb.selectBundle(MANUAL);
const worker = new Worker(bundle.mainWorker);
const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
const conn = await db.connect();
const r = await conn.query('SELECT 42 AS x, version() AS v');
console.log('wasm ok:', r.toArray().map(x => x.toJSON ? x.toJSON() : x));
await conn.close(); await db.terminate();
