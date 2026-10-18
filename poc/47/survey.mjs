// POC-47b: which modules actually bind core to a platform, and to which?
// Each module is bundled for platform=browser; node:* stays resolvable so a
// failure here means "this module needs Node", not "a dependency is missing".
import * as esbuild from 'esbuild';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const DIR = join(HERE, '.survey');
mkdirSync(DIR, { recursive: true });

const MODULES = {
  orchestration: `export const createAgent = () => ({ ask: async () => ({ sql: 'select 1' }) });`,
  semantic: `export const bind = (q) => ({ metric: q });`,
  guard: `export const assertReadOnly = (s) => s;`,
  admin: `export const createAdminHandler = () => async (req) => new Response('ok');`,
  tiering: `export const createTiering = (cfg) => ({ tiers: cfg.tiers });`,
  'connectors-http': `export const createHttpConnector = (cfg) => ({ kind: 'http', cfg });`,
  'connectors-s3': `export const createS3Connector = (cfg) => ({ kind: 's3-presigned', cfg });`,
  'engine-wasm': `export const createDuckDbWasm = async () => ({ kind: 'duckdb-wasm' });`,
  'cache-opfs': `export const createOpfsCache = () => ({ kind: 'opfs' });`,
  'connectors-pg': `import { connect } from 'node:net';\nexport const createPg = (cfg) => ({ kind: 'pg', connect: () => connect(5432, cfg.host) });`,
  'connectors-mysql': `import { createConnection } from 'node:net';\nexport const createMysql = (cfg) => ({ kind: 'mysql', connect: () => createConnection(3306, cfg.host) });`,
  'connectors-file': `import { readFile } from 'node:fs/promises';\nexport const createFile = (p) => ({ kind: 'file', read: () => readFile(p) });`,
  'engine-node': `import { statSync } from 'node:fs';\nexport const createDuckDbNode = () => ({ kind: 'duckdb-node', probe: statSync });`,
  'cache-file': `import { mkdirSync } from 'node:fs';\nexport const createFileCache = (d) => ({ kind: 'file-cache', init: () => mkdirSync(d, { recursive: true }) });`,
};

const rows = [];
for (const [name, src] of Object.entries(MODULES)) {
  const file = join(DIR, `${name}.mjs`);
  writeFileSync(file, src);
  let r;
  try {
    const out = await esbuild.build({
      entryPoints: [file], bundle: true, write: false, platform: 'browser',
      format: 'esm', minify: true, logLevel: 'silent', target: 'es2020',
      external: ['pg', 'mysql2', '@duckdb/*', '@aws-sdk/*', 'zod', 'ai'],
    });
    const code = out.outputFiles[0].text;
    r = { ok: true, bytes: Buffer.byteLength(code) };
  } catch (e) {
    const m = /Could not resolve "([^"]+)"/.exec(String(e.message));
    r = { ok: false, missing: m ? m[1] : String(e.message).split('\n')[0] };
  }
  const nodeSpec = [...src.matchAll(/from\s+['"](node:[^'"]+)['"]/g)].map((m) => m[1]);
  rows.push({ module: name, browserBundle: r.ok, nodeImports: nodeSpec, bytes: r.bytes ?? null, missing: r.missing ?? null });
}

const groups = {
  portable: rows.filter((x) => x.browserBundle).map((x) => x.module),
  nodeOnly: rows.filter((x) => !x.browserBundle).map((x) => x.module),
};
const byClass = {
  engine: rows.filter((x) => x.module.startsWith('engine')).filter((x) => !x.browserBundle).map((x) => x.module),
  connectors: rows.filter((x) => x.module.startsWith('connectors') && !x.browserBundle).map((x) => x.module),
  persistence: rows.filter((x) => x.module.startsWith('cache') && !x.browserBundle).map((x) => x.module),
};

const summary = {
  total: rows.length,
  portable: groups.portable.length,
  nodeOnly: groups.nodeOnly.length,
  nodeOnlyByClass: byClass,
  classes: Object.entries(byClass).filter(([, v]) => v.length).map(([k]) => k),
  connectorOnlyHypothesisHolds: byClass.engine.length === 0 && byClass.persistence.length === 0,
};

writeFileSync(join(HERE, 'survey.json'), JSON.stringify({ rows, summary }, null, 1));
for (const r of rows) {
  console.log((r.browserBundle ? 'PORTABLE ' : 'NODE-ONLY'), '|', r.module.padEnd(18),
    r.browserBundle ? `${r.bytes} B` : `needs ${r.missing}`);
}
console.log('---', JSON.stringify(summary));
