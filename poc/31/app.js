import * as duckdb from '@duckdb/duckdb-wasm';

const qs = new URLSearchParams(location.search);
const TAB = qs.get('tab') || 'A';
const MODE = qs.get('mode') || 'nolock';   // nolock | lock | ifavail
const DB = qs.get('db') || 'conc.db';
const out = { tab: TAB, mode: MODE, steps: [] };
const log = (k, v) => { out.steps.push([k, v]); };

const OPEN_MODE = qs.get('ro') === '1' ? duckdb.DuckDBAccessMode.READ_ONLY : duckdb.DuckDBAccessMode.READ_WRITE;
const openDb = async () => {
  const bundle = await duckdb.selectBundle({
    mvp: { mainModule: './duckdb-mvp.wasm', mainWorker: './duckdb-browser-mvp.worker.js' },
    eh:  { mainModule: './duckdb-eh.wasm',  mainWorker: './duckdb-browser-eh.worker.js' },
  });
  const worker = new Worker(bundle.mainWorker);
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  await db.open({ path: `opfs://${DB}`, accessMode: OPEN_MODE });
  return db;
};

async function work() {
  let db;
  try {
    db = await openDb(); log('open', 'ok');
  } catch (e) { log('open', 'ERR:' + String(e).slice(0, 120)); throw e; }
  const c = await db.connect();
  await c.query('CREATE TABLE IF NOT EXISTS t(tab VARCHAR, n INT)');
  // 3 批交错写入，放大竞争窗口
  for (let b = 0; b < 3; b++) {
    await c.query(`INSERT INTO t SELECT '${TAB}', range FROM range(100) tbl(range)`);
    await new Promise(r => setTimeout(r, 250));
  }
  log('inserted', 300);
  await c.query('CHECKPOINT');
  log('checkpoint', 'ok');
  // 同会话读
  const mid = Number((await c.query('SELECT count(*) c FROM t')).toArray()[0].c);
  log('count_same_session', mid);
  await db.terminate(); log('terminate', 'ok');
  // 重开读
  const db2 = await openDb();
  const c2 = await db2.connect();
  const rows = (await c2.query(`SELECT tab, count(*) c FROM t GROUP BY 1 ORDER BY 1`)).toArray()
        .map(r => [r.tab, Number(r.c)]);
  log('count_reopen', rows);
  const root = await navigator.storage.getDirectory();
  try { log('bytes', (await (await root.getFileHandle(DB)).getFile()).size); } catch { log('bytes', -1); }
  await db2.terminate();
}

async function run() {
  // 同步两标签页起跑
  // 绝对时间栅栏：所有标签页在同一毫秒起跑
  const startAt = Math.ceil((Date.now() + 1200) / 500) * 500;
  while (Date.now() < startAt) await new Promise(r => setTimeout(r, 20));
  log('sync', 'started-at-' + startAt);

  if (MODE === 'holdopen') {
    try {
      await navigator.locks.request('t2c.db', { mode: 'exclusive', ifAvailable: true }, async (lock) => {
        if (!lock) { log('lock', 'not-available'); return; }
        log('lock', 'leader');
        const db = await openDb(); log('open', 'ok');
        const c = await db.connect(); log('connect', 'ok');
        await new Promise(r => setTimeout(r, Number(qs.get('hold') || 8000)));
        log('holding_db_open', 'yes');
        const n = Number((await c.query('SELECT count(*) c FROM t')).toArray()[0].c);
        log('count_self', n);
        await db.terminate();
      });
    } catch (e) { log('result', 'failed:' + String(e).slice(0, 150)); }
    window.__done = out; return;
  }
  if (MODE === 'holdwrites') {
    try {
      await navigator.locks.request('t2c.db', { mode: 'exclusive', ifAvailable: true }, async (lock) => {
        if (!lock) { log('lock', 'not-available'); return; }
        log('lock', 'leader');
        const db = await openDb(); log('open', 'ok');
        const c = await db.connect();
        await c.query(`INSERT INTO t SELECT 'W', range FROM range(300) tbl(range)`);
        log('inserted_uncommitted', 300);
        await new Promise(r => setTimeout(r, Number(qs.get('hold') || 8000)));
        log('still_holding', 'yes');
      });
    } catch (e) { log('result', 'failed:' + String(e).slice(0, 140)); }
    window.__done = out; return;
  }
  if (MODE === 'reader') {
    try {
      const db = await openDb(); log('open_ro', 'ok');
      const c = await db.connect();
      const n = Number((await c.query('SELECT count(*) c FROM t')).toArray()[0].c);
      log('read_rows', n);
      await db.terminate(); log('result', 'reader-ok');
    } catch (e) { log('result', 'reader-failed:' + String(e).slice(0, 140)); }
    window.__done = out; return;
  }
  if (MODE === 'nolock') {
    try { await work(); log('result', 'completed'); }
    catch (e) { log('result', 'failed:' + String(e).slice(0, 140)); }
  } else if (MODE === 'lock') {
    try {
      await navigator.locks.request('t2c.db', { mode: 'exclusive' }, async () => {
        log('lock', 'acquired');
        await work();
        log('result', 'completed-under-lock');
      });
    } catch (e) { log('result', 'failed:' + String(e).slice(0, 140)); }
  } else if (MODE === 'wait') {
    // 选主 + 重试（验证 leader 崩溃后能否接管）
    const deadline = Date.now() + 15000;
    let gotIt = false;
    while (Date.now() < deadline && !gotIt) {
      await navigator.locks.request('t2c.db', { mode: 'exclusive', ifAvailable: true }, async (lock) => {
        if (!lock) return;
        gotIt = true;
        log('lock', 'leader-after-wait@' + Date.now());
        try { await work(); log('result', 'failover-leader-done'); }
        catch (e) { log('result', 'failover-failed:' + String(e).slice(0, 120)); }
      });
      if (!gotIt) await new Promise(r => setTimeout(r, 250));
    }
    if (!gotIt) log('result', 'never-acquired');
  } else {
    // 选主：拿不到锁就做 follower
    let got = false;
    await navigator.locks.request('t2c.db', { mode: 'exclusive', ifAvailable: true }, async (lock) => {
      if (!lock) { log('lock', 'not-available'); return; }
      got = true; log('lock', 'leader');
      await new Promise(r => setTimeout(r, Number(qs.get('hold') || 3000)));
      try { await work(); log('result', 'leader-done'); }
      catch (e) { log('result', 'leader-failed:' + String(e).slice(0, 140)); }
    });
    if (!got) log('result', 'follower-skip');
  }
  window.__done = out;
}

run().catch(e => { out.fatal = String(e).slice(0, 200); window.__done = out; });
