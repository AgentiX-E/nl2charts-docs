// POC-45: single package with subpaths vs three packages (core / node / browser).
// Self-contained: generates every layout, every mutation, then measures and gates.
import * as esbuild from 'esbuild';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runGates } from './check-platform.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const WORK = join(HERE, '.work');

const ENGINE_CONTRACT = `export interface Engine {
  readonly kind: string;
  query(sql: string): Promise<Record<string, unknown>[]>;
  close(): Promise<void>;
}
export const ENGINE_BRAND = Symbol.for('nl2charts.engine');
export const isEngine = (v: unknown): v is Engine =>
  typeof v === 'object' && v !== null && (v as Record<symbol, unknown>)[ENGINE_BRAND] === true;
`;

const AGENT_SRC = `export interface AgentConfig { readonly engine?: unknown; readonly llm?: unknown }
export interface Agent { readonly ask: (q: string) => Promise<{ sql: string }> }
export function createAgent(cfg: AgentConfig): Agent {
  return { ask: async (q: string) => ({ sql: \`select 1 /* \${q} */\` }) };
}
export function negotiate(): 'local' | 'remote' { return 'local'; }
`;

const DTS_INDEX = `export type { Engine } from './engine/contract';
export { isEngine, ENGINE_BRAND } from './engine/contract';
export interface AgentConfig { readonly engine?: unknown; readonly llm?: unknown }
export interface Agent { readonly ask: (q: string) => Promise<{ sql: string }> }
export declare function createAgent(cfg: AgentConfig): Agent;
export declare function negotiate(): 'local' | 'remote';
`;

const DTS_NODE = `import type { Engine } from './contract';
export declare function createDuckDbNode(cfg: { path: string }): Promise<Engine>;
`;

function corePkg(extraExports = {}, extra = {}) {
  return JSON.stringify({
    name: '@agentix-e/nl2charts-core', version: '1.0.0', type: 'module', sideEffects: false,
    exports: {
      '.': { types: './dist/index.d.ts', default: './src/index.ts' },
      './duckdb-node': { types: './dist/engine/node.d.ts', default: './src/engine/node.ts' },
      './duckdb-wasm': { types: './dist/engine/wasm.d.ts', default: './src/engine/wasm.ts' },
      './connectors/pg': { types: './dist/connectors/pg.d.ts', default: './src/connectors/pg.ts' },
      ...extraExports,
    },
    peerDependencies: { zod: '^3.23 || ^4', ai: '^7', '@duckdb/node-api': '1.5.6-r.1',
      '@duckdb/duckdb-wasm': '1.33.1-dev65.0', pg: '^8', mysql2: '^3', ...extra },
    peerDependenciesMeta: { '@duckdb/node-api': { optional: true }, '@duckdb/duckdb-wasm': { optional: true },
      pg: { optional: true }, mysql2: { optional: true } },
  }, null, 1);
}

// ---- L1: one package, platform capabilities behind subpaths -----------------
const L1 = {
  'core/package.json': corePkg(),
  'core/src/index.ts': `export type { Engine } from './engine/contract';\nexport { isEngine } from './engine/contract';\n${AGENT_SRC}`,
  'core/src/engine/contract.ts': ENGINE_CONTRACT,
  'core/src/engine/node.ts': `import { readFile } from 'node:fs/promises';
import type { Engine } from './contract';
import { ENGINE_BRAND } from './contract';
export async function createDuckDbNode(cfg: { path: string }): Promise<Engine> {
  await readFile(cfg.path).catch(() => null);
  return { kind: 'duckdb-node', query: async () => [], close: async () => {}, [ENGINE_BRAND]: true } as Engine;
}
`,
  'core/src/engine/wasm.ts': `import type { Engine } from './contract';
import { ENGINE_BRAND } from './contract';
export async function createDuckDbWasm(): Promise<Engine> {
  return { kind: 'duckdb-wasm', query: async () => [], close: async () => {}, [ENGINE_BRAND]: true } as Engine;
}
`,
  'core/src/connectors/pg.ts': `import { connect } from 'node:net';
export function createPgConnector(cfg: { host: string }) {
  return { kind: 'pg', connect: () => connect(5432, cfg.host) };
}
`,
  'core/dist/index.d.ts': DTS_INDEX,
  'core/dist/engine/contract.d.ts': `export interface Engine {
  readonly kind: string;
  query(sql: string): Promise<Record<string, unknown>[]>;
  close(): Promise<void>;
}
export declare const ENGINE_BRAND: unique symbol;
export declare const isEngine: (v: unknown) => v is Engine;
`,
  'core/dist/engine/node.d.ts': DTS_NODE,
  'core/dist/engine/wasm.d.ts': `import type { Engine } from './contract';
export declare function createDuckDbWasm(): Promise<Engine>;
`,
  'core/dist/connectors/pg.d.ts': `import { Socket } from 'node:net';
export declare function createPgConnector(cfg: { host: string }): { kind: string; connect: () => Socket };
`,
};

// ---- L2: core (neutral) + node (bindings) + browser (bindings) --------------
const L2 = {
  'core/package.json': JSON.stringify({
    name: '@agentix-e/nl2charts-core', version: '1.0.0', type: 'module', sideEffects: false,
    exports: { '.': { types: './dist/index.d.ts', default: './src/index.ts' } },
    peerDependencies: { zod: '^3.23 || ^4', ai: '^7' },
  }, null, 1),
  'core/src/index.ts': `export interface Engine {
  readonly kind: string;
  query(sql: string): Promise<Record<string, unknown>[]>;
  close(): Promise<void>;
}
export const ENGINE_BRAND = Symbol.for('nl2charts.engine');
export const isEngine = (v: unknown): v is Engine =>
  typeof v === 'object' && v !== null && (v as Record<symbol, unknown>)[ENGINE_BRAND] === true;
${AGENT_SRC}`,
  'core/dist/index.d.ts': DTS_INDEX.replace("from './engine/contract'", "from './contract'"),
  'core/dist/contract.d.ts': `export interface Engine {
  readonly kind: string;
  query(sql: string): Promise<Record<string, unknown>[]>;
  close(): Promise<void>;
}
export declare const ENGINE_BRAND: unique symbol;
export declare const isEngine: (v: unknown) => v is Engine;
`,
  'node/package.json': JSON.stringify({
    name: '@agentix-e/nl2charts-node', version: '1.0.0', type: 'module', sideEffects: false,
    exports: { '.': { types: './dist/index.d.ts', default: './src/index.ts' },
      './pg': { types: './dist/pg.d.ts', default: './src/pg.ts' } },
    dependencies: { '@agentix-e/nl2charts-core': 'workspace:^' },
    peerDependencies: { '@duckdb/node-api': '1.5.6-r.1', pg: '^8', mysql2: '^3' },
    peerDependenciesMeta: { '@duckdb/node-api': { optional: true }, pg: { optional: true }, mysql2: { optional: true } },
  }, null, 1),
  'node/src/index.ts': `import { readFile } from 'node:fs/promises';
import type { Engine } from '@agentix-e/nl2charts-core';
import { ENGINE_BRAND } from '@agentix-e/nl2charts-core';
export async function createDuckDbNode(cfg: { path: string }): Promise<Engine> {
  await readFile(cfg.path).catch(() => null);
  return { kind: 'duckdb-node', query: async () => [], close: async () => {}, [ENGINE_BRAND]: true } as Engine;
}
`,
  'node/src/pg.ts': `import { connect } from 'node:net';
export function createPgConnector(cfg: { host: string }) {
  return { kind: 'pg', connect: () => connect(5432, cfg.host) };
}
`,
  'node/dist/index.d.ts': `import type { Engine } from '@agentix-e/nl2charts-core';
export declare function createDuckDbNode(cfg: { path: string }): Promise<Engine>;
`,
  'node/dist/pg.d.ts': `import { Socket } from 'node:net';
export declare function createPgConnector(cfg: { host: string }): { kind: string; connect: () => Socket };
`,
  'browser/package.json': JSON.stringify({
    name: '@agentix-e/nl2charts-browser', version: '1.0.0', type: 'module', sideEffects: false,
    exports: { '.': { types: './dist/index.d.ts', default: './src/index.ts' } },
    dependencies: { '@agentix-e/nl2charts-core': 'workspace:^' },
    peerDependencies: { '@duckdb/duckdb-wasm': '1.33.1-dev65.0' },
  }, null, 1),
  'browser/src/index.ts': `import type { Engine } from '@agentix-e/nl2charts-core';
import { ENGINE_BRAND } from '@agentix-e/nl2charts-core';
export async function createDuckDbWasm(): Promise<Engine> {
  return { kind: 'duckdb-wasm', query: async () => [], close: async () => {}, [ENGINE_BRAND]: true } as Engine;
}
`,
  'browser/dist/index.d.ts': `import type { Engine } from '@agentix-e/nl2charts-core';
export declare function createDuckDbWasm(): Promise<Engine>;
`,
};

// ---- leak: driver type exposed on the public surface -----------------------
const LEAK = {
  ...L1,
  'core/src/index.ts': `import type { DuckDBConnection } from '@duckdb/node-api';
export type { DuckDBConnection };
export type { Engine } from './engine/contract';
export { isEngine } from './engine/contract';
${AGENT_SRC}`,
  'core/dist/index.d.ts': `import type { DuckDBConnection } from '@duckdb/node-api';
export type { DuckDBConnection };
${DTS_INDEX}`,
};

function write(root, files) {
  rmSync(root, { recursive: true, force: true });
  for (const [p, c] of Object.entries(files)) {
    const abs = join(root, p);
    mkdirSync(dirname(abs), { recursive: true });
    writeFileSync(abs, c);
  }
}

// ---- mutations: one per gate ----------------------------------------------
function mutations() {
  const m = {};
  m.PLT1 = { ...L1, 'core/src/index.ts': `import { readFile } from 'node:fs/promises';\nexport const __probe = readFile;\n${L1['core/src/index.ts']}` };
  m.PLT2 = {
    ...L1,
    'core/src/connectors/pg2.ts': `import pg from 'pg';\nexport const createPg2 = (cfg: { host: string }) => new pg.Client(cfg);\n`,
    'core/src/index.ts': `export { createPg2 } from './connectors/pg2';\n${L1['core/src/index.ts']}`,
  };
  m.PLT3 = LEAK;
  m.PLT4 = { ...L2, 'core/package.json': JSON.stringify({
    ...JSON.parse(L2['core/package.json']),
    dependencies: { '@agentix-e/nl2charts-node': 'workspace:^' },
  }, null, 1) };
  m.PLT5 = { ...L2, 'node/src/index.ts': `${L2['node/src/index.ts']}\nexport function createAgent() { return {}; }\n` };
  m.PLT6a = { ...L1, 'core/src/index.ts':
    `export class EngineBase { readonly kind = 'x'; }\nexport const isEngine = (v: unknown): boolean => v instanceof EngineBase;\n${AGENT_SRC}` };
  m.PLT6b = { ...L1, 'core/src/index.ts':
    `export const registry = new Map<string, unknown>();
export function register(k: string, v: unknown) { registry.set(k, v); }
export function resolve(k: string) { return registry.get(k) ?? null; }\n${L1['core/src/index.ts']}` };
  return m;
}

// ---- measurement: what a browser build actually contains -------------------
const APPS = {
  'l1-browser': { pkg: 'l1', lines: [
    `import { createAgent } from '@agentix-e/nl2charts-core';`,
    `import { createDuckDbWasm } from '@agentix-e/nl2charts-core/duckdb-wasm';`,
    `console.log(createAgent({}), createDuckDbWasm());`] },
  'l1-node': { pkg: 'l1', lines: [
    `import { createAgent } from '@agentix-e/nl2charts-core';`,
    `import { createDuckDbNode } from '@agentix-e/nl2charts-core/duckdb-node';`,
    `import { createPgConnector } from '@agentix-e/nl2charts-core/connectors/pg';`,
    `console.log(createAgent({}), createDuckDbNode({}), createPgConnector({}));`] },
  'l1-browser-misuse': { pkg: 'l1', lines: [
    `import { createPgConnector } from '@agentix-e/nl2charts-core/connectors/pg';`,
    `console.log(createPgConnector({}));`] },
  'l2-browser': { pkg: 'l2', lines: [
    `import { createAgent } from '@agentix-e/nl2charts-core';`,
    `import { createDuckDbWasm } from '@agentix-e/nl2charts-browser';`,
    `console.log(createAgent({}), createDuckDbWasm());`] },
  'l2-node': { pkg: 'l2', lines: [
    `import { createAgent } from '@agentix-e/nl2charts-core';`,
    `import { createDuckDbNode } from '@agentix-e/nl2charts-node';`,
    `import { createPgConnector } from '@agentix-e/nl2charts-node/pg';`,
    `console.log(createAgent({}), createDuckDbNode({}), createPgConnector({}));`] },
  'l2-browser-misuse': { pkg: 'l2', lines: [
    `import { createDuckDbNode } from '@agentix-e/nl2charts-node';`,
    `console.log(createDuckDbNode({}));`] },
};

const ALIAS = {
  l1: {
    '@agentix-e/nl2charts-core': join(WORK, 'l1/core/src/index.ts'),
    '@agentix-e/nl2charts-core/duckdb-node': join(WORK, 'l1/core/src/engine/node.ts'),
    '@agentix-e/nl2charts-core/duckdb-wasm': join(WORK, 'l1/core/src/engine/wasm.ts'),
    '@agentix-e/nl2charts-core/connectors/pg': join(WORK, 'l1/core/src/connectors/pg.ts'),
  },
  l2: {
    '@agentix-e/nl2charts-core': join(WORK, 'l2/core/src/index.ts'),
    '@agentix-e/nl2charts-node': join(WORK, 'l2/node/src/index.ts'),
    '@agentix-e/nl2charts-node/pg': join(WORK, 'l2/node/src/pg.ts'),
    '@agentix-e/nl2charts-browser': join(WORK, 'l2/browser/src/index.ts'),
  },
};

async function measure() {
  mkdirSync(join(WORK, 'apps'), { recursive: true });
  const rows = [];
  for (const [name, spec] of Object.entries(APPS)) {
    const entry = join(WORK, 'apps', `${name}.js`);
    writeFileSync(entry, spec.lines.join('\n') + '\nexport const __ok = true;\n');
    const platform = name.includes('browser') ? 'browser' : 'node';
    try {
      const out = await esbuild.build({
        entryPoints: [entry], bundle: true, write: false, platform, format: 'esm',
        minify: true, logLevel: 'silent', alias: ALIAS[spec.pkg],
        target: platform === 'browser' ? 'es2020' : 'node20',
      });
      const code = out.outputFiles[0].text;
      rows.push({ case: name, platform, ok: true, bytes: Buffer.byteLength(code),
        hasPg: /pg-pool|pg-protocol|new pg\.Client|connect\(5432/.test(code),
        hasNodeBuiltin: /node:(fs|net|tls|dns)/.test(code) });
    } catch (e) {
      rows.push({ case: name, platform, ok: false, error: String(e.message).split('\n')[0].slice(0, 110) });
    }
  }
  return rows;
}

// ---- main -----------------------------------------------------------------
const fixtures = { l1: L1, l2: L2, leak: LEAK, ...Object.fromEntries(Object.entries(mutations()).map(([k, v]) => [`mut-${k}`, v])) };
for (const [name, files] of Object.entries(fixtures)) write(join(WORK, name), files);

const measured = await measure();

const gateRows = [];
for (const name of Object.keys(fixtures)) {
  const r = await runGates(join(WORK, name));
  gateRows.push({ fixture: name, red: r.violations.map((v) => v.id), details: r.violations });
}

const result = {
  meta: { esbuild: (await import('esbuild/package.json', { with: { type: 'json' } })).default.version,
    node: process.version, note: 'fixtures are generated from this file; d.ts are the published type surface under test' },
  measure: measured,
  gates: gateRows,
  summary: {
    identicalBytes: measured.find((m) => m.case === 'l1-browser')?.bytes === measured.find((m) => m.case === 'l2-browser')?.bytes,
    baselineGreen: gateRows.filter((g) => g.fixture === 'l1' || g.fixture === 'l2').every((g) => g.red.length === 0),
    mutationsCaught: gateRows.filter((g) => g.fixture.startsWith('mut-')).filter((g) => g.red.length > 0).length,
    mutationsTotal: gateRows.filter((g) => g.fixture.startsWith('mut-')).length,
  },
};
writeFileSync(join(HERE, 'results.json'), JSON.stringify(result, null, 1));

console.log('--- measure ---');
for (const m of measured) console.log(String(m.case).padEnd(22), m.platform.padEnd(8),
  m.ok ? `${String(m.bytes).padStart(5)} B  pg=${m.hasPg} node:*=${m.hasNodeBuiltin}` : `FAIL ${m.error}`);
console.log('--- gates ---');
for (const g of gateRows) console.log(g.fixture.padEnd(12), g.red.length ? g.red.join(',') : 'GREEN');
console.log('--- summary ---', JSON.stringify(result.summary));
