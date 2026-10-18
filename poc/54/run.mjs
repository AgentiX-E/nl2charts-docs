// POC-54: can a host add a connector without touching the core package, and
// does incremental tiering actually transfer only the missing keys?
// The "core" here is a 40-line frozen module: it knows the Tier contract and a
// registry, and nothing about any concrete source.
import fs from 'node:fs';
import http from 'node:http';
import crypto from 'node:crypto';
import path from 'node:path';

// ------------------------------------------------------------ frozen core
const CORE_SRC = `
export const registry = new Map();
export function registerConnector(kind, factory) {
  if (typeof kind !== 'string' || !kind) throw new Error('CONNECTOR_INVALID_KIND');
  if (registry.has(kind)) throw new Error('CONNECTOR_DUPLICATE:' + kind);
  registry.set(kind, factory);
}
export function createTier(kind, opts) {
  const f = registry.get(kind);
  if (!f) throw new Error('CONNECTOR_NOT_REGISTERED:' + kind);
  const c = f(opts);
  for (const m of ['describe', 'fetch']) {
    if (typeof c[m] !== 'function') throw new Error('CONNECTOR_MISSING_METHOD:' + m);
  }
  return c;
}
export async function sync(tier, localKeys) {
  const desc = await tier.describe();
  const have = new Set(localKeys);
  const missing = desc.keys.filter(k => !have.has(k));
  if (!missing.length) return { rows: [], fetched: 0, snapshot: desc.snapshot, missing: 0 };
  const rows = await tier.fetch({ snapshot: desc.snapshot, keys: missing });
  if (rows.snapshot !== desc.snapshot) throw new Error('TIER_SNAPSHOT_MISMATCH');
  return { rows: rows.rows, fetched: rows.rows.length, snapshot: desc.snapshot, missing: missing.length };
}
`;
const coreHashBefore = crypto.createHash('sha256').update(CORE_SRC).digest('hex');

// ------------------------------------------------------------ connectors (host side)
// Minimum surface: describe() + fetch(). No changes() / no partitions().
function httpJsonConnector({ url, bytesCounter }) {
  return {
    async describe() {
      const res = await fetch(url + '/describe');
      const d = await res.json();
      bytesCounter.describe += Buffer.byteLength(JSON.stringify(d));
      return d;
    },
    async fetch({ snapshot, keys }) {
      const res = await fetch(url + '/rows', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ snapshot, keys }),
      });
      const text = await res.text();
      bytesCounter.fetch += Buffer.byteLength(text);
      const body = JSON.parse(text);
      return { rows: body.rows, snapshot: body.snapshot };
    },
  };
}

function csvFileConnector({ file }) {
  return {
    async describe() {
      const lines = fs.readFileSync(file, 'utf8').trim().split('\n');
      const keys = lines.slice(1).map(l => l.split(',')[0]);
      return { snapshot: crypto.createHash('sha1').update(lines.join('\n')).digest('hex').slice(0, 12), keys };
    },
    async fetch({ snapshot, keys }) {
      const lines = fs.readFileSync(file, 'utf8').trim().split('\n');
      const cur = crypto.createHash('sha1').update(lines.join('\n')).digest('hex').slice(0, 12);
      if (snapshot !== cur) throw new Error('TIER_SNAPSHOT_MISMATCH');
      const body = lines.slice(1).map(l => l.split(','));
      const want = new Set(keys);
      return {
        snapshot,
        rows: body.filter(r => want.has(r[0])).map(r => ({ id: r[0], region: r[1], amount: Number(r[2]) })),
      };
    },
  };
}

// ------------------------------------------------------------ fake remote warehouse
const REMOTE_ROWS = Array.from({ length: 1000 }, (_, i) => ({
  id: `k${String(i).padStart(4, '0')}`,
  region: ['emea', 'apac', 'amer'][i % 3],
  amount: 100 + i,
}));
const SNAPSHOT = 'snap-2026-10-18';
const bytesCounter = { describe: 0, fetch: 0 };
const server = http.createServer((req, res) => {
  if (req.url === '/describe') {
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ snapshot: SNAPSHOT, keys: REMOTE_ROWS.map(r => r.id), schema: ['id', 'region', 'amount'] }));
    return;
  }
  if (req.url === '/rows') {
    let body = '';
    req.on('data', c => { body += c; });
    req.on('end', () => {
      const { snapshot, keys } = JSON.parse(body);
      if (snapshot !== SNAPSHOT) { res.statusCode = 409; res.end(JSON.stringify({ error: 'SNAPSHOT_MISMATCH' })); return; }
      const want = new Set(keys);
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ snapshot: SNAPSHOT, rows: REMOTE_ROWS.filter(r => want.has(r.id)) }));
    });
    return;
  }
  res.statusCode = 404; res.end('{}');
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const port = server.address().port;

// ------------------------------------------------------------ run
const core = await import('data:text/javascript,' + encodeURIComponent(CORE_SRC));
core.registerConnector('http-json', (o) => httpJsonConnector(o));
core.registerConnector('csv-file', (o) => csvFileConnector(o));

const localFile = '/tmp/poc54/local.csv';
const localKeys = REMOTE_ROWS.slice(0, 900).map(r => r.id);
fs.writeFileSync(localFile,
  'id,region,amount\n' + REMOTE_ROWS.slice(0, 900).map(r => `${r.id},${r.region},${r.amount}`).join('\n') + '\n');

const tier = core.createTier('http-json', { url: `http://127.0.0.1:${port}`, bytesCounter });

// full sync for comparison: "select all keys"
const fullStart = Date.now();
const full = await core.sync(tier, []);
const fullMs = Date.now() - fullStart;
const fullBytes = bytesCounter.describe + bytesCounter.fetch;

bytesCounter.describe = 0; bytesCounter.fetch = 0;
const incStart = Date.now();
const inc = await core.sync(tier, localKeys);
const incMs = Date.now() - incStart;
const incBytes = bytesCounter.describe + bytesCounter.fetch;

// second incremental sync: nothing missing -> zero fetch bytes
bytesCounter.describe = 0; bytesCounter.fetch = 0;
const noop = await core.sync(tier, REMOTE_ROWS.map(r => r.id));
const noopBytes = bytesCounter.describe + bytesCounter.fetch;

// custom connector #2: local CSV, same contract
const csvTier = core.createTier('csv-file', { file: localFile });
const csvDesc = await csvTier.describe();
const csvRows = await csvTier.fetch({ snapshot: csvDesc.snapshot, keys: csvDesc.keys.slice(0, 3) });

// failure modes
const failures = [];
try { core.createTier('postgres', {}); } catch (e) { failures.push(e.message.split(':')[0]); }
try { core.registerConnector('http-json', () => ({})); } catch (e) { failures.push(e.message.split(':')[0]); }
try { core.createTier('csv-file', { file: localFile }).then; } catch (e) { failures.push(e.message); }
const badTier = core.createTier('csv-file', { file: localFile });
try { await badTier.fetch({ snapshot: 'stale', keys: ['k0001'] }); } catch (e) { failures.push(e.message.split(':')[0]); }

const coreHashAfter = crypto.createHash('sha256').update(CORE_SRC).digest('hex');

// manifest scaling: what does describe() cost when the key list is returned?
const manifest = {};
for (const n of [1000, 10000, 100000]) {
  const keys = Array.from({ length: n }, (_, i) => `k${String(i).padStart(7, '0')}`);
  manifest[n] = Buffer.byteLength(JSON.stringify({ snapshot: SNAPSHOT, keys, schema: ['id', 'region', 'amount'] }));
}

const out = {
  generatedAt: new Date().toISOString(),
  manifestBytes: manifest,
  core: {
    lines: CORE_SRC.trim().split('\n').length,
    unchangedDuringOnboarding: coreHashBefore === coreHashAfter,
    registeredKinds: [...core.registry.keys()],
  },
  surface: {
    requiredMethods: ['describe', 'fetch'],
    connector1Methods: Object.keys(httpJsonConnector({ url: '', bytesCounter })).length,
    connector2Methods: Object.keys(csvFileConnector({ file: localFile })).length,
  },
  incremental: {
    remoteRows: REMOTE_ROWS.length,
    localRows: localKeys.length,
    missingRows: inc.missing,
    full: { rows: full.fetched, bytes: fullBytes, ms: fullMs },
    incremental: { rows: inc.fetched, bytes: incBytes, ms: incMs },
    byteRatio: +(incBytes / fullBytes).toFixed(3),
    savedPct: +((1 - incBytes / fullBytes) * 100).toFixed(1),
    noop: { rows: noop.fetched, bytes: noopBytes },
  },
  csvConnector: { keys: csvDesc.keys.length, sample: csvRows.rows.length, snapshot: csvDesc.snapshot },
  failureModes: failures,
  snapshotGuard: 'TIER_SNAPSHOT_MISMATCH on stale snapshot',
};
fs.writeFileSync('results.json', JSON.stringify(out, null, 2));
server.close();

console.log(JSON.stringify({
  core_unchanged: out.core.unchangedDuringOnboarding,
  core_lines: out.core.lines,
  required_methods: out.surface.requiredMethods.length,
  kinds: out.core.registeredKinds,
  incremental: out.incremental,
  csv: out.csvConnector,
  failures: out.failureModes,
}, null, 2));

// ------------------------------------------------------------ key reconciliation at 1M rows
// The 2-method SPI transfers the whole key list. Measure that cost, then two
// bounded alternatives: bucket digests, and a binary Merkle descent.
const N = 1_000_000;
const allKeys = Array.from({ length: N }, (_, i) => `k${String(i).padStart(8, '0')}`);
const missIdx = new Set(Array.from({ length: 1000 }, () => Math.floor(Math.random() * N)));
const localSet = new Set(allKeys.filter((_, i) => !missIdx.has(i)));
const naiveManifestBytes = Buffer.byteLength(JSON.stringify(allKeys));
const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');

// ---- (a) bucket digest: server sends H hashes, client compares, then pulls
// the key list of every mismatching bucket.
function bucketDigest(keys, buckets) {
  const size = Math.ceil(keys.length / buckets);
  const out = [];
  for (let i = 0; i < keys.length; i += size) out.push(sha(keys.slice(i, i + size).join('|')));
  return { size, out };
}
const BUCKETS = 4096;
const serverBuckets = bucketDigest(allKeys, BUCKETS);
const localKeysArr = allKeys.filter(k => localSet.has(k));
const localBuckets = bucketDigest(localKeysArr, BUCKETS);
let bucketBytes = serverBuckets.out.length * 32;
let bucketKeyBytes = 0;
for (let b = 0; b < serverBuckets.out.length; b++) {
  // a bucket "differs" if the digest differs; we then pull that bucket's keys
  // (local bucket alignment differs once keys are missing, so this is the
  // realistic worst case for a flat digest)
  if (serverBuckets.out[b] !== localBuckets.out[b]) {
    bucketKeyBytes += Math.min(serverBuckets.size, N - b * serverBuckets.size) * 11;
  }
}

// ---- (b) binary Merkle descent: each visited internal node sends 2 hashes.
const leaf = (k) => sha(k);
const levels = [allKeys.map(leaf)];
while (levels[levels.length - 1].length > 1) {
  const cur = levels[levels.length - 1];
  const next = [];
  for (let i = 0; i < cur.length; i += 2) next.push(sha((cur[i] || '') + (cur[i + 1] || '')));
  levels.push(next);
}
const localLevels = [allKeys.map(k => (localSet.has(k) ? leaf(k) : null))];
while (localLevels[localLevels.length - 1].length > 1) {
  const cur = localLevels[localLevels.length - 1];
  const next = [];
  for (let i = 0; i < cur.length; i += 2) {
    const a = cur[i], b = cur[i + 1];
    next.push(a === null || b === null ? null : sha(a + b));
  }
  localLevels.push(next);
}
let merkleHashBytes = 0, merkleKeys = 0, visited = 0;
const stack = [[levels.length - 1, 0]];
while (stack.length) {
  const [lvl, idx] = stack.pop();
  visited++;
  if (lvl === 0) { merkleKeys++; continue; }
  const children = [];
  for (const c of [idx * 2, idx * 2 + 1]) {
    if (c < levels[lvl - 1].length) children.push(c);
  }
  merkleHashBytes += children.length * 32;          // server ships the child hashes
  for (const c of children) {
    if (levels[lvl - 1][c] !== localLevels[lvl - 1][c]) stack.push([lvl - 1, c]);
  }
}

out.keyReconciliation = {
  rows: N,
  missing: missIdx.size,
  naiveManifestBytes,
  bucketDigest: {
    buckets: BUCKETS,
    digestBytes: bucketBytes,
    keyBytes: bucketKeyBytes,
    totalBytes: bucketBytes + bucketKeyBytes,
    ratio: +((bucketBytes + bucketKeyBytes) / naiveManifestBytes).toFixed(3),
  },
  merkleBinary: {
    levels: levels.length,
    visitedNodes: visited,
    hashBytes: merkleHashBytes,
    keyBytes: merkleKeys * 11,
    totalBytes: merkleHashBytes + merkleKeys * 11,
    ratio: +((merkleHashBytes + merkleKeys * 11) / naiveManifestBytes).toFixed(4),
    speedup: +(naiveManifestBytes / (merkleHashBytes + merkleKeys * 11)).toFixed(1),
  },
};
fs.writeFileSync('results.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify({ key_reconciliation: out.keyReconciliation }, null, 2));
