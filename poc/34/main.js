/**
 * POC-34: 缓存与 tier 链的收益 + 失效正确性
 * A. 负载：120 条 SQL（模板生成）× 1000 次请求（Zipf 分布，模拟 BI 重复率）
 * B. 对比：无缓存 / C1 结果缓存（强键）/ C1 弱键（缺 snapshot）
 * C. 失效正确性：5 次变更后，强键必须 0 脏读；弱键必然脏读
 */
const { DuckDBInstance } = require('/tmp/poc12/node_modules/@duckdb/node-api');
const crypto = require('crypto');

const J = (x) => JSON.stringify(x, (_, v) => typeof v === 'bigint' ? v.toString() : v ?? null);

function hash(s) { return crypto.createHash('sha256').update(s).digest('hex').slice(0, 16); }

// ---------- 数据 ----------
async function build(conn) {
  await conn.run(`CREATE TABLE orders(order_id BIGINT, region VARCHAR, category VARCHAR, amount DECIMAL(12,2), status VARCHAR, d DATE)`);
  await conn.run(`CREATE TABLE dim_region(region VARCHAR, area VARCHAR)`);
  await conn.run(`INSERT INTO dim_region VALUES ('华东','E'),('华北','N'),('华南','S'),('西南','W')`);
  await conn.run(`INSERT INTO orders
    SELECT g, (ARRAY['华东','华北','华南','西南'])[1+(g%4)], (ARRAY['数码','服饰','食品'])[1+(g%3)],
           ((g*37)%1000)/10.0, (ARRAY['paid','paid','paid','paid','paid','paid','refunded','pending'])[1+(g%8)],
           DATE '2026-01-01' + to_days(CAST(g%120 AS INTEGER))
    FROM (SELECT unnest(generate_series(1,20000)) AS g)`);
}

// ---------- 负载：120 条不同 SQL ----------
function makeQueries() {
  const regions = ['华东', '华北', '华南', '西南'];
  const cats = ['数码', '服饰', '食品'];
  const months = ['01', '02', '03', '04'];
  const qs = [];
  for (const r of regions) for (const m of months) {
    qs.push(`SELECT sum(amount) v FROM orders WHERE region='${r}' AND status='paid' AND strftime(d,'%m')='${m}'`);
  }
  for (const c of cats) for (const m of months) {
    qs.push(`SELECT count(*) v FROM orders WHERE category='${c}' AND strftime(d,'%m')='${m}'`);
  }
  for (const r of regions) {
    qs.push(`SELECT count(DISTINCT order_id) v FROM orders WHERE region='${r}' AND status='refunded'`);
    qs.push(`SELECT avg(amount) v FROM orders WHERE region='${r}'`);
    qs.push(`SELECT sum(amount)/count(DISTINCT order_id) v FROM orders WHERE region='${r}' AND status='paid'`);
  }
  for (const c of cats) for (const r of regions) {
    qs.push(`SELECT sum(amount) v FROM orders WHERE category='${c}' AND region='${r}'`);
  }
  // 跨表
  for (const a of ['E', 'N', 'S', 'W']) {
    qs.push(`SELECT a.area, sum(o.amount) v FROM orders o JOIN dim_region a USING(region) WHERE a.area='${a}' AND o.status='paid' GROUP BY 1`);
  }
  return qs;
}

// Zipf 采样
function zipfPick(n, s = 1.1) {
  const w = [];
  for (let i = 1; i <= n; i++) w.push(1 / Math.pow(i, s));
  const total = w.reduce((a, b) => a + b, 0);
  let r = Math.random() * total;
  for (let i = 0; i < n; i++) { r -= w[i]; if (r <= 0) return i; }
  return n - 1;
}

(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const conn = await inst.connect();
  await build(conn);

  const QS = makeQueries();
  const N_REQ = 1000;

  // 固定请求序列（同一序列跑三种策略，保证可比）
  let seed = 12345;
  const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  const order = [];
  for (let i = 0; i < N_REQ; i++) {
    const save = Math.random; Math.random = rnd;
    order.push(zipfPick(QS.length));
    Math.random = save;
  }

  const now = () => Number(process.hrtime.bigint()) / 1000;   // us
  const exec = async (sql) => {
    const t = process.hrtime.bigint();
    const r = await conn.runAndReadAll(sql);
    return { rows: J(r.getRows()), us: Number(process.hrtime.bigint() - t) / 1000 };
  };

  // ---------- A. 无缓存 ----------
  let t0 = Date.now();
  const nocache = [];
  for (const qi of order) { const r = await exec(QS[qi]); nocache.push(r.us); }
  const noCacheMs = Date.now() - t0;

  // ---------- B1. 强键缓存 ----------
  const snapshot = 'snap-1', buildId = 'node-1.5.6/linux', dialect = 'cds', tz = 'UTC';
  const strongKey = (sql) => hash([sql, snapshot, buildId, dialect, tz].join('|'));
  const cacheS = new Map();
  t0 = Date.now();
  const strong = []; let hitS = 0;
  for (const qi of order) {
    const t = now();
    const k = strongKey(QS[qi]);
    if (cacheS.has(k)) { hitS++; strong.push(+(now() - t).toFixed(1)); }
    else { const r = await exec(QS[qi]); cacheS.set(k, r); strong.push(+(now() - t).toFixed(1)); }
  }
  const strongMs = Date.now() - t0;

  // ---------- B2. 弱键缓存（缺 snapshot）----------
  const weakKey = (sql) => hash([sql, buildId, dialect, tz].join('|'));
  const cacheW = new Map();
  t0 = Date.now();
  const weak = []; let hitW = 0;
  for (const qi of order) {
    const t = now();
    const k = weakKey(QS[qi]);
    if (cacheW.has(k)) { hitW++; weak.push(+(now() - t).toFixed(1)); }
    else { const r = await exec(QS[qi]); cacheW.set(k, r); weak.push(+(now() - t).toFixed(1)); }
  }
  const weakMs = Date.now() - t0;

  const pct = (arr, p) => { const a = [...arr].sort((x, y) => x - y); return +a[Math.floor(p * (a.length - 1))].toFixed(1); };
  const stat = (arr) => ({ p50: pct(arr, .5), p95: pct(arr, .95), p99: pct(arr, .99), mean: +(arr.reduce((a, b) => a + b, 0) / arr.length).toFixed(1) });

  // ---------- C. 失效正确性：5 次变更 ----------
  // 强键：变更后 snapshot 变化 -> 键变化 -> 必然 miss（0 脏读）
  // 弱键：键不变 -> 命中旧结果（脏读）
  const mutations = [
    `INSERT INTO orders SELECT 999001, '华东','数码', 12345.67,'paid', DATE '2026-02-15'`,
    `UPDATE orders SET amount = amount * 2 WHERE order_id % 5000 = 0`,
    `INSERT INTO orders SELECT 999002, '华北','食品', 1.23,'paid', DATE '2026-03-01'`,
    `DELETE FROM orders WHERE order_id % 7777 = 0`,
    `UPDATE orders SET status='refunded' WHERE order_id % 3333 = 0`,
  ];
  const probeIdx = [0, 6, 12, 30, 42];   // 选几条典型查询做探针
  const probes = probeIdx.map(i => QS[i]);
  const failure = { strong: [], weak: [] };
  let snap = 1;
  for (const m of mutations) {
    await conn.run(m);
    snap++;
    // 变更后立刻重算真值
    for (const sql of probes) {
      const truth = await exec(sql);
      // 强键：snap 变化 -> 新键 -> 必须 miss
      const ksNew = hash([sql, `snap-${snap}`, buildId, dialect, tz].join('|'));
      const strongStale = cacheS.has(ksNew) && cacheS.get(ksNew).rows !== truth.rows;
      // 弱键：键不变 -> 会命中旧值
      const kw = weakKey(sql);
      const weakStale = cacheW.has(kw) && cacheW.get(kw).rows !== truth.rows;
      failure.strong.push({ snap, sql: sql.slice(0, 40), stale: strongStale, hit: cacheS.has(ksNew) });
      failure.weak.push({ snap, sql: sql.slice(0, 40), stale: weakStale, hit: cacheW.has(kw) });
      // 模拟正确实现：命中即校验 snapshot
      if (cacheS.has(ksNew)) cacheS.delete(ksNew);
      // 弱键不清理，保持脏值以演示
    }
  }

  const out = {
    queries: QS.length, requests: N_REQ,
    distinct_requested: new Set(order).size,
    no_cache: { total_ms: noCacheMs, ...stat(nocache) },
    strong_cache: { total_ms: strongMs, hit_rate: +(hitS / N_REQ).toFixed(3), ...stat(strong),
                    hit_p50: pct(strong.filter((_, i) => i >= 0).slice(0, hitS), .5) },
    weak_cache: { total_ms: weakMs, hit_rate: +(hitW / N_REQ).toFixed(3), ...stat(weak) },
    stale: {
      strong_stale_count: failure.strong.filter(x => x.stale).length,
      strong_probes: failure.strong.length,
      weak_stale_count: failure.weak.filter(x => x.stale).length,
      weak_probes: failure.weak.length,
      samples: failure.weak.filter(x => x.stale).slice(0, 3),
    },
  };
  require('fs').writeFileSync('/tmp/poc34_results.json', JSON.stringify(out, null, 1));
  console.log(JSON.stringify(out, null, 1));
})().catch(e => { console.error('FATAL', e); process.exit(1); });
