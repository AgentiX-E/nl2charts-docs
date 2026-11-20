// POC-47: can the browser satisfy tiering without any node-only connector?
// Builds the browser tier as a real browser bundle, then runs that bundle
// against a server that owns the engine and the credentials.
import * as esbuild from 'esbuild';
import { createServer } from 'node:http';
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createTierHandler } from './src/server-handler.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, '.work');
mkdirSync(OUT, { recursive: true });

const rows = [];
const add = (check, value, expected, note = '') => {
  const pass = JSON.stringify(value) === JSON.stringify(expected);
  rows.push({ check, value, expected, pass, note });
};

// ---- 1) the browser tier must bundle with zero node dependencies ----------
const bundleFile = join(OUT, 'browser-tier.mjs');
let bundleInfo;
try {
  const out = await esbuild.build({
    entryPoints: [join(HERE, 'src/browser-tier.mjs')],
    bundle: true, write: false, platform: 'browser', format: 'esm',
    minify: true, logLevel: 'silent', target: 'es2020', metafile: true,
  });
  const code = out.outputFiles[0].text;
  writeFileSync(bundleFile, code);
  const imports = Object.values(out.metafile.outputs)[0].imports.map((i) => i.path);
  bundleInfo = {
    ok: true,
    bytes: Buffer.byteLength(code),
    hasNodeBuiltin: /node:(fs|net|tls|dns|http2)/.test(code),
    hasDriver: /pg-pool|mysql2|duckdb-node|node-api/.test(code),
    imports,
  };
} catch (e) {
  bundleInfo = { ok: false, error: String(e.message).split('\n')[0] };
}
add('browser tier bundles for platform=browser', bundleInfo.ok, true);
add('browser bundle contains node:*', bundleInfo.hasNodeBuiltin, false, 'PLT1 analogue');
add('browser bundle contains a driver', bundleInfo.hasDriver, false, 'PLT2 analogue');

// ---- 2) run that bundle as if it were the browser -------------------------
const { createHttpTier } = await import(pathToFileURL(bundleFile).href + '?v=1');

// ---- 3) the server owns the engine and the credentials --------------------
const handler = createTierHandler({ snapshotId: 'snap-2026-10-18' });
const server = createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const init = { method: req.method, headers: req.headers };
  if (chunks.length) init.body = Buffer.concat(chunks);
  const resp = await handler(new Request(`http://${req.headers.host}${req.url}`, init));
  const headers = {};
  resp.headers.forEach((v, k) => { headers[k] = v; });
  res.writeHead(resp.status, headers);
  res.end(Buffer.from(await resp.arrayBuffer()));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
const endpoint = `http://127.0.0.1:${port}/tier/v1`;

const tier = createHttpTier({ endpoint });

// 3a) describe: capability only, never credentials
const d = await tier.describe();
add('describe exposes snapshotId', typeof d.snapshotId, 'string');
add('describe leaks no connection string', JSON.stringify(d).includes('postgres://'), false);
add('describe reports authoritative tier', d.tiers[0].role, 'authoritative');

// 3b) local has 300 of 1000 rows -> backfill pulls the gap
const pulled = await tier.backfill('select * from orders', 300);
add('backfill fetches rows over plain HTTP', pulled.fetched, 1000);
add('backfill carries the snapshot', pulled.snapshotId, 'snap-2026-10-18');
add('backfill rows are structurally usable', typeof pulled.rows[0].amount, 'number');

// 3c) nothing missing -> no request at all
const again = await tier.backfill('select * from orders', 1000);
add('no-op when local is complete', again.reason, 'local-complete');

// 3d) the bridge is a SQL surface, so the guard must run server-side
async function expectCode(fn) {
  try { await fn(); return 'no-error'; } catch (e) { return e.code ?? e.message; }
}
add('write statement is rejected', await expectCode(() => tier.backfill('drop table orders', -1)), 'STATEMENT_NOT_ALLOWED');
add('attach is rejected', await expectCode(() => tier.backfill("attach 'x.db' as x", -1)), 'STATEMENT_NOT_ALLOWED');
add('non-select is rejected', await expectCode(() => tier.backfill('with c as (select 1) delete from t', -1)), 'STATEMENT_NOT_ALLOWED');

// 3e) upstream down -> explicit error, never a silent empty result
const dead = createHttpTier({ endpoint: 'http://127.0.0.1:1/tier/v1' });
add('upstream down yields TIER_UNAVAILABLE', await expectCode(() => dead.describe()), 'TIER_UNAVAILABLE');

server.close();

const summary = {
  total: rows.length,
  pass: rows.filter((r) => r.pass).length,
  browserBundleBytes: bundleInfo.bytes ?? null,
  browserImports: bundleInfo.imports ?? [],
  zeroNodeDeps: bundleInfo.hasNodeBuiltin === false && bundleInfo.hasDriver === false,
  endToEnd: rows.filter((r) => r.check.startsWith('backfill')).every((r) => r.pass),
  guardHolds: rows.filter((r) => r.check.includes('rejected')).every((r) => r.pass),
};

writeFileSync(join(HERE, 'results.json'), JSON.stringify({ meta: { node: process.version }, rows, summary }, null, 1));
for (const r of rows) console.log((r.pass ? 'PASS' : 'FAIL'), '|', r.check.padEnd(44), '->', JSON.stringify(r.value));
console.log('---', JSON.stringify(summary));
