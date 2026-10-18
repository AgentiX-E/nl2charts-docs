const fs = require('fs');
const p = '/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';
const { createDuckDB, NODE_RUNTIME, ConsoleLogger } = require(p + '/duckdb-node-blocking.cjs');
const { DuckDBInstance } = require('/tmp/poc1/node_modules/@duckdb/node-api');

const CASES = [
  // numeric semantics
  ['num_round_half', `SELECT round(2.5) a, round(3.5) b, round(-2.5) c, round(-3.5) d`],
  ['num_int_div', `SELECT 5/2 a, 5//2 b`],
  ['num_decimal_div', `SELECT (1::DECIMAL(10,4) / 3)::VARCHAR a`],
  ['num_float', `SELECT (0.1::DOUBLE + 0.2::DOUBLE)::VARCHAR a`],
  ['num_overflow', `SELECT CAST(1e19 AS BIGINT) a`],
  ['num_sum_type', `SELECT typeof(sum(x)) t, sum(x)::VARCHAR s FROM (VALUES (1),(2)) v(x)`],
  // date/time semantics
  ['dt_week_start', `SELECT strftime(date_trunc('week', DATE '2026-10-18'), '%Y-%m-%d (%a)') a`],
  ['dt_dow', `SELECT extract(dow FROM DATE '2026-10-18') a, extract(isodow FROM DATE '2026-10-18') b`],
  ['dt_month_end', `SELECT (DATE '2026-01-31' + INTERVAL 1 MONTH)::VARCHAR a`],
  ['dt_diff_boundary', `SELECT date_diff('day', TIMESTAMP '2026-01-01 23:00:00', TIMESTAMP '2026-01-02 01:00:00') a`],
  ['dt_month_name', `SELECT strftime(DATE '2026-10-18', '%B') a`],
  ['dt_timezone_set', `SET TimeZone='Asia/Shanghai'`],
  ['dt_current', `SELECT current_date::VARCHAR d, strftime(now(), '%Y-%m-%dT%H:%M:%S%z') n`],
  ['dt_dst', `SELECT strftime(TIMESTAMPTZ '2026-03-08 06:59:59+00' AT TIME ZONE 'America/New_York', '%Y-%m-%d %H:%M %Z') a`],
  // strings / unicode
  ['str_emoji_len', `SELECT length('😀') a, length('中文') b, octet_length('😀') c`],
  ['str_upper', `SELECT upper('ß') a, lower('İ') b`],
  ['str_substr', `SELECT substring('😀ab', 1, 1) a, substr('中文测试', 2, 2) b`],
  ['str_like_escape', `SELECT 'a_b' LIKE 'a\\_b' ESCAPE '\\' a`],
  ['str_collate', `SELECT string_agg(x, ',' ORDER BY x COLLATE "en_US") s FROM (VALUES ('b'),('A'),('a')) t(x)`],
  ['str_cn_sort', `SELECT string_agg(x, ',' ORDER BY x) s FROM (VALUES ('上海'),('北京'),('广州')) t(x)`],
  // json
  ['json_key_order', `SELECT json('{"b":2,"a":1}') a`],
  ['json_dup_keys', `SELECT json('{"a":1,"a":2}') a`],
  ['json_big_int', `SELECT json('{"n":9007199254740993}') a, ('{"n":9007199254740993}'::JSON->>'n') b`],
  ['json_unicode', `SELECT json('{"k":"中文😀"}') a`],
  // hash / nondeterminism
  ['hash_text', `SELECT hash('abc') a, hash('中文') b`],
  ['hash_num', `SELECT hash(123) a, hash(123.45) b`],
  ['random_fn', `SELECT random() a`],
  ['uuid_fn', `SELECT uuid() a`],
  // order stability
  ['order_no_orderby', `SELECT x FROM (VALUES (1),(2),(3)) t(x)`],
  ['agg_list_order', `SELECT list(x) a FROM (VALUES (3),(1),(2)) t(x)`],
  ['first_last', `SELECT first(x) a, last(x) b FROM (VALUES (3),(1),(2)) t(x)`],
];

(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const nat = await inst.connect();
  const db = await createDuckDB({ mvp: { mainModule: p + '/duckdb-mvp.wasm' }, eh: { mainModule: p + '/duckdb-eh.wasm' } }, new ConsoleLogger(), NODE_RUNTIME);
  await db.instantiate();
  const w = db.connect();

  const rows = [];
  for (const [name, sql] of CASES) {
    const one = async (fn) => {
      try { const r = await fn(); return { ok: true, v: String(r) }; }
      catch (e) { return { ok: false, v: String(e.message).split('\n')[0].slice(0, 110) }; }
    };
    const a = await one(async () => {
      const r = await nat.runAndReadAll(sql);
      return JSON.stringify(r.getRowObjects(), (_, v) => typeof v === 'bigint' ? v.toString() : v);
    });
    const b = await one(async () => {
      const t = w.query(sql);
      const names = t.schema.fields.map(f => f.name);
      const plain = (x) => {
        if (typeof x === 'bigint') return x.toString();
        if (x && typeof x === 'object') {
          if (Array.isArray(x)) return x.map(plain);
          if ('value' in x && 'scale' in x) return String(Number(x.value) / 10 ** Number(x.scale));
          const o = {}; for (const k of Object.keys(x)) o[k] = plain(x[k]); return o;
        }
        return x;
      };
      return JSON.stringify(t.toArray().map(r => Object.fromEntries(names.map(n => [n, plain(r[n])]))));
    });
    const same = a.ok === b.ok && (a.ok ? a.v === b.v : true);
    rows.push({ name, same, node: a.v.slice(0, 220), wasm: b.v.slice(0, 220) });
    if (!same) console.log(`[DIFF:${name}]\n  node=${a.v}\n  wasm=${b.v}`);
  }
  console.log(`CASES ${rows.filter(r => r.same).length}/${rows.length} identical`);

  // ---- Parquet cross-engine ----
  await nat.run(`CREATE TABLE t(id INT, amt DECIMAL(12,2), ts TIMESTAMPTZ, s VARCHAR)`);
  await nat.run(`INSERT INTO t VALUES (1, 10.10, TIMESTAMPTZ '2026-10-01 00:00:00+00', '中文'), (2, 20.20, TIMESTAMPTZ '2026-10-02 00:00:00+00', '😀')`);
  await nat.run(`COPY t TO '/tmp/poc15/x_zstd.parquet' (FORMAT parquet, COMPRESSION zstd)`);
  const buf = fs.readFileSync('/tmp/poc15/x_zstd.parquet');
  let pq = 'n/a';
  try {
    db.registerFileBuffer('x_zstd.parquet', new Uint8Array(buf));
    const t = w.query(`SELECT count(*) c, sum(amt)::VARCHAR s, string_agg(s, ',') g FROM 'x_zstd.parquet'`);
    pq = JSON.stringify(t.toArray().map(r => r.toJSON ? 'row' : String(r)) ) + ' | raw=' + t.toArray().length;
  } catch (e) { pq = 'ERR ' + String(e.message).split('\n')[0].slice(0, 120); }
  console.log('PARQUET_ZSTD_NODE->WASM', pq);

  // ---- .duckdb file cross-engine (storage version) ----
  await nat.run(`ATTACH '/tmp/poc15/native.duckdb' AS nd`);
  await nat.run(`CREATE TABLE nd.t2 AS SELECT 42 AS x`);
  await nat.run(`DETACH nd`);
  let dbf = 'n/a';
  try {
    const dbBuf = fs.readFileSync('/tmp/poc15/native.duckdb');
    db.registerFileBuffer('native.duckdb', new Uint8Array(dbBuf));
    w.query(`ATTACH 'native.duckdb' AS nd2`);
    dbf = JSON.stringify(w.query('SELECT * FROM nd2.main.t2').toArray().map(x => x.toJSON ? x.toJSON() : x));
  } catch (e) { dbf = 'ERR ' + String(e.message).split('\n')[0].slice(0, 140); }
  console.log('DUCKDB_FILE_NODE->WASM', dbf);

  fs.writeFileSync('/tmp/poc15/results.json', JSON.stringify({ cases: rows, parquet: pq, duckdbFile: dbf }, null, 1));
})().catch(e => { console.error('FAIL', e); process.exit(1); });
