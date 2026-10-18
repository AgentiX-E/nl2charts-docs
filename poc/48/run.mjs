// POC-48: split only the Node side (core + node) vs one dual-runtime core.
// Measures: how much of the core surface a browser cannot use, peer surface,
// install footprint, and whether the driver upgrade couples to core.
import * as esbuild from 'esbuild';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const W = join(HERE, '.work');

// module bodies -------------------------------------------------------------
const M = {
  orchestration: `export const createAgent = () => ({ ask: async () => ({ sql: 'select 1' }) });`,
  semantic: `export const bind = (q) => ({ metric: q });`,
  guard: `export const assertReadOnly = (s) => s;`,
  admin: `export const createAdminHandler = () => async () => new Response('ok');`,
  tiering: `export const createTiering = (c) => ({ tiers: c.tiers });`,
  'http': `export const createHttpConnector = (c) => ({ kind: 'http', c });`,
  's3': `export const createS3Connector = (c) => ({ kind: 's3', c });`,
  'duckdb-wasm': `export const createDuckDbWasm = async () => ({ kind: 'wasm' });`,
  'opfs': `export const createOpfsCache = () => ({ kind: 'opfs' });`,
  'duckdb-node': `import { statSync } from 'node:fs';\nexport const createDuckDbNode = () => ({ kind: 'duckdb-node', p: statSync });`,
  'pg': `import { connect } from 'node:net';\nexport const createPg = (c) => ({ kind: 'pg', c });`,
  'mysql': `import { createConnection } from 'node:net';\nexport const createMysql = (c) => ({ kind: 'mysql', c });`,
  'file': `import { readFile } from 'node:fs/promises';\nexport const createFile = (p) => ({ kind: 'file', p });`,
  'cache-file': `import { mkdirSync } from 'node:fs';\nexport const createFileCache = (d) => ({ kind: 'cache', d });`,
};

const PORTABLE = ['orchestration', 'semantic', 'guard', 'admin', 'tiering', 'http', 's3', 'duckdb-wasm', 'opfs'];
const NODE_ONLY = ['duckdb-node', 'pg', 'mysql', 'file', 'cache-file'];

// layout A: one core with every subpath
const A = {};
for (const k of [...PORTABLE, ...NODE_ONLY]) A[`core/src/${k}.mjs`] = M[k];
A['core/package.json'] = JSON.stringify({
  name: '@agentix-e/nl2charts-core', version: '1.0.0', type: 'module', sideEffects: false,
  exports: Object.fromEntries([...PORTABLE, ...NODE_ONLY].map((k) => [`./${k}`, `./src/${k}.mjs`])),
  peerDependencies: { zod: '^3', ai: '^7', '@duckdb/node-api': '1.5.6-r.1', '@duckdb/duckdb-wasm': '1.33', pg: '^8', mysql2: '^3' },
}, null, 1);

// layout B: core keeps only portable capabilities, node owns the rest
const B = {};
for (const k of PORTABLE) B[`core/src/${k}.mjs`] = M[k];
B['core/package.json'] = JSON.stringify({
  name: '@agentix-e/nl2charts-core', version: '1.0.0', type: 'module', sideEffects: false,
  exports: Object.fromEntries(PORTABLE.map((k) => [`./${k}`, `./src/${k}.mjs`])),
  peerDependencies: { zod: '^3', ai: '^7', '@duckdb/duckdb-wasm': '1.33' },
}, null, 1);
for (const k of NODE_ONLY) B[`node/src/${k}.mjs`] = M[k];
B['node/package.json'] = JSON.stringify({
  name: '@agentix-e/nl2charts-node', version: '1.0.0', type: 'module', sideEffects: false,
  exports: Object.fromEntries(NODE_ONLY.map((k) => [`./${k}`, `./src/${k}.mjs`])),
  dependencies: { '@agentix-e/nl2charts-core': 'workspace:^' },
  peerDependencies: { '@duckdb/node-api': '1.5.6-r.1', pg: '^8', mysql2: '^3' },
}, null, 1);

function write(root, files) {
  rmSync(root, { recursive: true, force: true });
  for (const [p, c] of Object.entries(files)) {
    const abs = join(root, p); mkdirSync(dirname(abs), { recursive: true }); writeFileSync(abs, c);
  }
}
write(join(W, 'A'), A);
write(join(W, 'B'), B);

// does each exported entry bundle for a browser? -----------------------------
async function browserOk(file) {
  try {
    await esbuild.build({
      entryPoints: [file], bundle: true, write: false, platform: 'browser',
      format: 'esm', minify: true, logLevel: 'silent', target: 'es2020',
      external: ['pg', 'mysql2', '@duckdb/*', 'zod', 'ai'],
    });
    return true;
  } catch { return false; }
}

async function audit(layout) {
  const root = join(W, layout);
  const rows = [];
  for (const side of ['core', 'node']) {
    const pj = join(root, side, 'package.json');
    try {
      const p = JSON.parse(require('node:fs').readFileSync(pj, 'utf8'));
      for (const sub of Object.keys(p.exports)) {
        rows.push({ pkg: side, sub, browser: await browserOk(join(root, side, p.exports[sub])) });
      }
    } catch { /* package absent in this layout */ }
  }
  return rows;
}
const { readFileSync } = await import('node:fs');
globalThis.require = (await import('node:module')).createRequire(import.meta.url);

const rowsA = await audit('A');
const rowsB = await audit('B');

function summarize(rows, label) {
  const core = rows.filter((r) => r.pkg === 'core');
  const node = rows.filter((r) => r.pkg === 'node');
  return {
    layout: label,
    coreSubpaths: core.length,
    coreBrowserUsable: core.filter((r) => r.browser).length,
    coreUnusableRatio: core.length ? +(core.filter((r) => !r.browser).length / core.length).toFixed(2) : 0,
    nodeSubpaths: node.length,
    nodeBrowserUsable: node.filter((r) => r.browser).length,
  };
}

const sA = summarize(rowsA, 'A one core');
const sB = summarize(rowsB, 'B core+node');

// package.json surfaces -----------------------------------------------------
function surface(layout) {
  const out = {};
  for (const side of ['core', 'node']) {
    try {
      const p = JSON.parse(readFileSync(join(W, layout, side, 'package.json'), 'utf8'));
      out[side] = {
        peers: Object.keys(p.peerDependencies ?? {}),
        driversInPeers: Object.keys(p.peerDependencies ?? {}).filter((k) => /^(pg|mysql2|@duckdb\/(node-api|duckdb-wasm))$/.test(k)),
        subpaths: Object.keys(p.exports ?? {}).length,
      };
    } catch { /* absent */ }
  }
  return out;
}
const fA = surface('A');
const fB = surface('B');

// which package must release when a driver bumps? ---------------------------
const bumpCoupling = {
  A: ['core'],                                   // pg is a core peer -> core re-releases
  B: ['node'],                                   // pg is a node peer  -> core untouched
};

const result = {
  meta: { node: process.version },
  layouts: [sA, sB],
  surfaces: { A: fA, B: fB },
  browserInstall: { A: ['core'], B: ['core'] },
  nodeInstall: { A: ['core'], B: ['core', 'node'] },
  driverBumpReleases: bumpCoupling,
  summary: {
    coreSurfaceCleanA: sA.coreUnusableRatio,
    coreSurfaceCleanB: sB.coreUnusableRatio,
    peerDriversInCore: { A: fA.core.driversInPeers.length, B: fB.core.driversInPeers.length },
    extraPackagesForNode: 1,
    extraDependencyEdges: 1,
    extraInstallsForBrowser: 0,
    structuralGuarantee: sB.coreUnusableRatio === 0 && sB.nodeBrowserUsable === 0,
  },
};
writeFileSync(join(HERE, 'results.json'), JSON.stringify(result, null, 1));

console.log('A  core subpaths', sA.coreSubpaths, '| browser-usable', sA.coreBrowserUsable, '| unusable ratio', sA.coreUnusableRatio);
console.log('B  core subpaths', sB.coreSubpaths, '| browser-usable', sB.coreBrowserUsable, '| unusable ratio', sB.coreUnusableRatio);
console.log('B  node subpaths', sB.nodeSubpaths, '| browser-usable', sB.nodeBrowserUsable, '(must be 0)');
console.log('peers: A core', fA.core.peers.join(','), '| B core', fB.core.peers.join(','));
console.log('driver bump re-releases:', JSON.stringify(bumpCoupling));
console.log('---', JSON.stringify(result.summary));
