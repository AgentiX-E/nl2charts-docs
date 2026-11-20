const { DuckDBInstance } = require('/tmp/poc12/node_modules/@duckdb/node-api');
const fs = require('fs');
const path = '/tmp/poc22';
fs.mkdirSync(path + '/tmp', { recursive: true });

async function scenario(label, config) {
  const inst = await DuckDBInstance.create(':memory:', config);
  const c = await inst.connect();
  const t0 = Date.now();
  await c.run(`CREATE TABLE t AS
    SELECT i AS id, (i % 20) AS region, ((i * 37) % 100000) / 100.0 AS amount,
           TIMESTAMP '2026-01-01' + CAST(i % 365 AS INTEGER) * INTERVAL 1 DAY AS ts
    FROM range(10000000) tbl(i)`);
  const tBuild = Date.now() - t0;

  const t1 = Date.now();
  const agg = await c.runAndReadAll(`SELECT region, count(*) n, sum(amount) s FROM t GROUP BY 1 ORDER BY 1`);
  const tAgg = Date.now() - t1;

  const t2 = Date.now();
  const dq = await c.runAndReadAll(`SELECT count(DISTINCT id) d FROM t`);
  const tDistinct = Date.now() - t2;

  const t3 = Date.now();
  await c.run(`COPY t TO '${path}/t_${label}.parquet' (FORMAT parquet, COMPRESSION zstd)`);
  const tWrite = Date.now() - t3;
  const pqSize = fs.statSync(`${path}/t_${label}.parquet`).size;

  const t4 = Date.now();
  const rd = await c.runAndReadAll(`SELECT count(*) c, sum(amount) s FROM '${path}/t_${label}.parquet'`);
  const tRead = Date.now() - t4;

  const rss = process.resourceUsage().maxRSS / 1024; // MB
  console.log(JSON.stringify({ label, config, buildMs: tBuild, aggMs: tAgg, distinctMs: tDistinct,
    parquetWriteMs: tWrite, parquetMB: +(pqSize/1048576).toFixed(1), parquetReadMs: tRead,
    rows: agg.getRows().length, distinct: String(dq.getRows()[0][0]),
    parquetCount: String(rd.getRows()[0][0]), maxRSSMB: +rss.toFixed(0) }));
}

(async () => {
  const which = process.argv[2] || 'default';
  const CFG = { default: {}, mem1g: { memory_limit: '1GB', temp_directory: path + '/tmp' }, mem512m: { memory_limit: '512MB', temp_directory: path + '/tmp' } };
  await scenario(which, CFG[which]);
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
