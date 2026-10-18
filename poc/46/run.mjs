// POC-46: what happens when two physical copies of core coexist.
// Self-contained: writes two copies, then probes identity and registry behaviour.
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const WORK = join(HERE, '.work');

const CORE_SRC = `export const ENGINE_BRAND = Symbol.for('nl2charts.engine');
export class EngineBase {
  constructor(kind) { this.kind = kind; this[ENGINE_BRAND] = true; }
  async query() { return []; }
  async close() {}
}
export const isEngine = (v) => typeof v === 'object' && v !== null && (v[ENGINE_BRAND]) === true;
export function createAgent(cfg) {
  if (cfg.engine && !isEngine(cfg.engine)) throw new Error('NOT_AN_ENGINE');
  return { ask: async (q) => ({ sql: 'select 1' }) };
}
// naive registry: one Map per physical copy
export const NAIVE = new Map();
export function naiveRegister(k, v) { NAIVE.set(k, v); }
export function naiveResolve(k) { return NAIVE.get(k) ?? null; }
// shared registry: process-wide, keyed by a registered symbol
const KEY = Symbol.for('nl2charts.registry');
export const SHARED = (globalThis[KEY] ??= new Map());
export function register(k, v) { SHARED.set(k, v); }
export function resolve(k) { return SHARED.get(k) ?? null; }
`;

function writeCore(dir, version) {
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'package.json'), JSON.stringify({
    name: '@agentix-e/nl2charts-core', version, type: 'module', main: 'index.js',
  }, null, 1));
  writeFileSync(join(dir, 'index.js'), CORE_SRC);
}

writeCore(join(WORK, 'core-a'), '1.0.0');
writeCore(join(WORK, 'core-b'), '1.0.9');

const A = await import(pathToFileURL(join(WORK, 'core-a/index.js')).href + '?copy=a');
const B = await import(pathToFileURL(join(WORK, 'core-b/index.js')).href + '?copy=b');

// the "-node" package builds an engine through copy B
const engine = new B.EngineBase('duckdb-node');

const rows = [];
const add = (check, value, expected, note) => rows.push({ check, value, expected, pass: JSON.stringify(value) === JSON.stringify(expected), note });

add('engine instanceof EngineBase (copy A)', engine instanceof A.EngineBase, false,
  'instanceof is per-realm and per-copy, so it can never cross a copy boundary');
add('copy A isEngine(engine built by B)', A.isEngine(engine), true,
  'the brand is a registered symbol, so both copies read the same key');
add('copy B isEngine(same object)', B.isEngine(engine), true, 'sanity');
add('Symbol.for identity across copies', A.ENGINE_BRAND === B.ENGINE_BRAND, true,
  'global symbol registry returns the same symbol');

let accepted = 'accepted';
try { A.createAgent({ engine }); } catch (e) { accepted = 'rejected: ' + e.message; }
add('createAgent (copy A) accepts engine from B', accepted, 'accepted',
  'brand-based acceptance survives the split');

B.naiveRegister('pg', () => 'pg-engine');
add('module-level Map: A sees B registration', A.naiveResolve('pg') !== null, false,
  'module state is duplicated per copy -- silent failure');

B.register('pg', () => 'pg-engine');
add('globalThis registry: A sees B registration', A.resolve('pg') !== null, true,
  'the only implementation that spans copies');

const summary = {
  total: rows.length,
  pass: rows.filter((r) => r.pass).length,
  brandSurvives: rows.filter((r) => r.check.includes('isEngine') || r.check.includes('Symbol.for')).every((r) => r.pass),
  naiveRegistrySplits: rows.find((r) => r.check.includes('module-level Map'))?.value === false,
  sharedRegistryWorks: rows.find((r) => r.check.includes('globalThis'))?.value === true,
};

writeFileSync(join(HERE, 'results.json'), JSON.stringify({ meta: { node: process.version }, rows, summary }, null, 1));
for (const r of rows) console.log((r.pass ? 'PASS' : 'FAIL'), '|', r.check.padEnd(44), '->', JSON.stringify(r.value));
console.log('---', JSON.stringify(summary));
