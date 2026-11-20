import * as duckdb from '@duckdb/duckdb-wasm';
const out = { ok: false };
const openDb = async () => {
  const bundle = await duckdb.selectBundle({
    mvp: { mainModule: './duckdb-mvp.wasm', mainWorker: './duckdb-browser-mvp.worker.js' },
    eh:  { mainModule: './duckdb-eh.wasm',  mainWorker: './duckdb-browser-eh.worker.js' },
  });
  const worker = new Worker(bundle.mainWorker);
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  await db.open({ path: 'opfs://poc23.db', accessMode: duckdb.DuckDBAccessMode.READ_WRITE });
  return db;
};
try {
  let db = await openDb();
  let conn = await db.connect();
  await conn.query('CREATE TABLE IF NOT EXISTS t(x INT)');
  out.rowsBefore = Number((await conn.query('SELECT count(*) c FROM t')).toArray()[0].c);
  const root0 = await navigator.storage.getDirectory();
  const sz = async (n) => { try { return (await (await root0.getFileHandle(n)).getFile()).size; } catch { return -1; } };
  out.bytesBeforeAnyWrite = await sz('poc23.db');
  if (out.rowsBefore === 0) {
    await conn.query('INSERT INTO t SELECT range FROM range(1000) tbl(range)');
    out.bytesAfterInsertBeforeCheckpoint = await sz('poc23.db');
    await conn.query('CHECKPOINT');
    out.bytesAfterCheckpoint = await sz('poc23.db');
  }
  out.rowsAfter = Number((await conn.query('SELECT count(*) c FROM t')).toArray()[0].c);
  const root = await navigator.storage.getDirectory();
  const sizeOf = async (n) => { try { return (await (await root.getFileHandle(n)).getFile()).size; } catch { return -1; } };
  out.bytesAfterCheckpoint = await sizeOf('poc23.db');
  await db.terminate();
  out.bytesAfterClose = await sizeOf('poc23.db');
  out.walBytesAfterClose = await sizeOf('poc23.db.wal');
  db = await openDb(); conn = await db.connect();
  out.rowsAfterReopen = Number((await conn.query('SELECT count(*) c FROM t')).toArray()[0].c);
  await db.terminate();
  out.ok = true;
} catch (e) { out.error = String(e).slice(0, 300); }
window.__done = out;
