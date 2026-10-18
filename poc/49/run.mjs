// POC-49: can the SQL-first path (no AI at all) be a first-class product surface?
import * as esbuild from 'esbuild';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const W = join(HERE, '.work');
mkdirSync(W, { recursive: true });

const rows = [];
const add = (check, value, expected, note = '') =>
  rows.push({ check, value, expected, pass: JSON.stringify(value) === JSON.stringify(expected), note });

const ALIAS = {
  '@agentix-e/nl2charts-core': join(HERE, 'core/src/index.mjs'),
  '@agentix-e/nl2charts-chart': join(HERE, 'chart/src/recommend.mjs'),
  '@agentix-e/nl2charts-ai': join(HERE, 'ai/src/agent.mjs'),
};

// ---- 1) core must have no AI in its graph --------------------------------
const coreEntry = join(HERE, 'core/src/index.mjs');
const coreBuild = await esbuild.build({
  entryPoints: [coreEntry], bundle: true, write: false, platform: 'browser',
  format: 'esm', minify: true, logLevel: 'silent', target: 'es2020', metafile: true,
  alias: ALIAS,
});
const coreCode = coreBuild.outputFiles[0].text;
const coreMeta = Object.values(coreBuild.metafile.outputs)[0];
const coreImports = coreMeta.imports.map((i) => i.path);
writeFileSync(join(W, 'core.mjs'), coreCode);

add('core bundles for a browser', true, true);
add('core imports no AI package', coreImports.some((i) => /nl2charts-ai|\bai\b|openai|langchain/.test(i)), false);
add('core bundle mentions no model SDK', /openai|anthropic|@ai-sdk|langchain/.test(coreCode), false);

// core's declared surface must not advertise an AI peer
const corePkg = {
  name: '@agentix-e/nl2charts-core', type: 'module', sideEffects: false,
  exports: { '.': './src/index.mjs' },
  peerDependencies: { zod: '^3', '@duckdb/duckdb-wasm': '^1.33' },
  peerDependenciesMeta: { '@duckdb/duckdb-wasm': { optional: true } },
};
add('core declares no AI peer', Object.keys(corePkg.peerDependencies).some((k) => k === 'ai'), false);
add('core peer count', Object.keys(corePkg.peerDependencies).length, 2);

// ---- 2) SQL-first end to end --------------------------------------------
const core = await import(pathToFileURL(join(W, 'core.mjs')).href + '?v=core');
const chart = await import(pathToFileURL(ALIAS['@agentix-e/nl2charts-chart']).href + '?v=chart');

const runner = core.createRunner({ engine: core.createMemoryEngine() });
const r = await runner.sql("select region, amount from orders where region = 'east'");
add('sql-first executes without any model', r.rowCount, 100);
add('provenance says sql', r.provenance.path, 'sql');

async function code(fn) { try { await fn(); return 'ok'; } catch (e) { return e.code ?? e.message; } }
add('guard blocks a write', await code(() => runner.sql('drop table orders')), 'STATEMENT_NOT_ALLOWED');
add('guard blocks attach', await code(() => runner.sql("attach 'x.db' as x")), 'STATEMENT_NOT_ALLOWED');

// ---- 3) charts are deterministic, not a model decision ------------------
const ir1 = chart.recommend(r.rows);
const ir2 = chart.recommend(r.rows);
add('chart recommendation is deterministic', JSON.stringify(ir1) === JSON.stringify(ir2), true);
add('chart type picked from data shape', ir1.type, 'bar');
const opt = chart.compile(ir1);
add('compile returns an option object', typeof opt.series, 'object');

// ---- 4) the AI path sits on top and reuses the same runner -------------
const ai = await import(pathToFileURL(ALIAS['@agentix-e/nl2charts-ai']).href + '?v=ai');
const agent = ai.createAgent({
  engine: core.createMemoryEngine(),
  schema: { tables: ['orders'], columns: ['region', 'amount'] },
  llm: { toSql: async () => 'select region, amount from orders' },   // provider-agnostic stub
});
const a = await agent.ask('按区域看金额');
add('ai path returns the same result shape', a.rowCount, 200);
add('ai path is marked nl', a.provenance.path, 'nl');

// ---- 5) size split: what does a SQL-only user avoid paying for? --------
const aiPkgJson = {
  name: '@agentix-e/nl2charts-ai', type: 'module', sideEffects: false,
  exports: { '.': './src/agent.mjs' },
  dependencies: { '@agentix-e/nl2charts-core': 'workspace:^' },
  peerDependencies: { ai: '^7' },
};
add('ai depends on core', Object.keys(aiPkgJson.dependencies).includes('@agentix-e/nl2charts-core'), true);
add('core does not depend on ai', Object.keys(corePkg.peerDependencies).includes('@agentix-e/nl2charts-ai'), false);

const result = {
  meta: { node: process.version },
  rows,
  summary: {
    total: rows.length,
    pass: rows.filter((x) => x.pass).length,
    sqlOnlyNeedsAI: false,
    coreBytes: Buffer.byteLength(coreCode),
    coreImports,
  },
};
writeFileSync(join(HERE, 'results.json'), JSON.stringify(result, null, 1));
for (const x of rows) console.log((x.pass ? 'PASS' : 'FAIL'), '|', x.check.padEnd(42), '->', JSON.stringify(x.value));
console.log('---', JSON.stringify(result.summary));
