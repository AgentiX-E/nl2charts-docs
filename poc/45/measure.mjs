// POC-45: single-package-subpath (L1) vs three-package (L2) -- what actually differs?
import * as esbuild from 'esbuild';
import { writeFileSync, mkdirSync, writeFileSync as wf } from 'node:fs';

const HERE = new URL('.', import.meta.url).pathname;

// ---- entries -------------------------------------------------------------
function writeEntries(dir, imports, name) {
  mkdirSync(dir, { recursive: true });
  const body = imports.map((i) => i).join('\n') + `\nexport const __ok = true;\n`;
  wf(`${dir}/${name}`, body);
}

// L1 browser: root entry + wasm subpath
writeEntries(`${HERE}L1/app`, [
  `import { createAgent } from '@agentix-e/nl2charts-core';`,
  `import { createDuckDbWasm } from '@agentix-e/nl2charts-core/duckdb-wasm';`,
  `console.log(createAgent({}), createDuckDbWasm({}));`,
], 'browser.js');
// L1 node: root entry + node subpath + pg subpath
writeEntries(`${HERE}L1/app`, [
  `import { createAgent } from '@agentix-e/nl2charts-core';`,
  `import { createDuckDbNode } from '@agentix-e/nl2charts-core/duckdb-node';`,
  `import { createPgConnector } from '@agentix-e/nl2charts-core/connectors/pg';`,
  `console.log(createAgent({}), createDuckDbNode({}), createPgConnector({}));`,
], 'node.js');
// L1 misuse: browser build that touches the pg subpath
writeEntries(`${HERE}L1/app`, [
  `import { createPgConnector } from '@agentix-e/nl2charts-core/connectors/pg';`,
  `console.log(createPgConnector({}));`,
], 'browser-misuse.js');

// L2 browser / node
writeEntries(`${HERE}L2/app`, [
  `import { createAgent } from '@agentix-e/nl2charts-core';`,
  `import { createDuckDbWasm } from '@agentix-e/nl2charts-browser';`,
  `console.log(createAgent({}), createDuckDbWasm({}));`,
], 'browser.js');
writeEntries(`${HERE}L2/app`, [
  `import { createAgent } from '@agentix-e/nl2charts-core';`,
  `import { createDuckDbNode } from '@agentix-e/nl2charts-node';`,
  `import { createPgConnector } from '@agentix-e/nl2charts-node/pg';`,
  `console.log(createAgent({}), createDuckDbNode({}), createPgConnector({}));`,
], 'node.js');
// L2 misuse: browser build that imports the node package
writeEntries(`${HERE}L2/app`, [
  `import { createDuckDbNode } from '@agentix-e/nl2charts-node';`,
  `console.log(createDuckDbNode({}));`,
], 'browser-misuse.js');

const aliasL1 = {
  '@agentix-e/nl2charts-core': `${HERE}L1/core/src/index.ts`,
  '@agentix-e/nl2charts-core/duckdb-node': `${HERE}L1/core/src/engine/node.ts`,
  '@agentix-e/nl2charts-core/duckdb-wasm': `${HERE}L1/core/src/engine/wasm.ts`,
  '@agentix-e/nl2charts-core/connectors/pg': `${HERE}L1/core/src/connectors/pg.ts`,
};
const aliasL2 = {
  '@agentix-e/nl2charts-core': `${HERE}L2/core/src/index.ts`,
  '@agentix-e/nl2charts-node': `${HERE}L2/node/src/index.ts`,
  '@agentix-e/nl2charts-node/pg': `${HERE}L2/node/src/pg.ts`,
  '@agentix-e/nl2charts-browser': `${HERE}L2/browser/src/index.ts`,
};

async function build(entry, platform, alias) {
  try {
    const out = await esbuild.build({
      entryPoints: [entry], bundle: true, write: false, platform, format: 'esm',
      minify: true, alias, logLevel: 'silent',
      target: platform === 'browser' ? 'es2020' : 'node20',
    });
    const code = out.outputFiles[0].text;
    return {
      ok: true,
      bytes: Buffer.byteLength(code),
      hasPg: /pg-pool|pg-protocol|new pg\.Client|\bconnect\(5432/.test(code),
      hasNodeBuiltin: /node:(fs|net|tls|dns)/.test(code),
      nodeBuiltinsSeen: [...new Set((code.match(/node:[a-z/]+/g) || []))].slice(0, 6),
    };
  } catch (e) {
    return { ok: false, error: String(e.message).split('\n').slice(0, 2).join(' | ') };
  }
}

const cases = [
  ['L1 browser (root + subpath)', `${HERE}L1/app/browser.js`, 'browser', aliasL1],
  ['L1 node (root + subpath)', `${HERE}L1/app/node.js`, 'node', aliasL1],
  ['L1 browser misuse (pg)', `${HERE}L1/app/browser-misuse.js`, 'browser', aliasL1],
  ['L2 browser (core + browser)', `${HERE}L2/app/browser.js`, 'browser', aliasL2],
  ['L2 node (core + node)', `${HERE}L2/app/node.js`, 'node', aliasL2],
  ['L2 browser misuse (node pkg)', `${HERE}L2/app/browser-misuse.js`, 'browser', aliasL2],
];

const res = [];
for (const [name, entry, platform, alias] of cases) {
  const r = await build(entry, platform, alias);
  res.push({ case: name, platform, ...r });
  console.log(name.padEnd(32), platform.padEnd(8), r.ok ? `${String(r.bytes).padStart(6)} B  pg=${r.hasPg} node:*=${r.hasNodeBuiltin}` : `FAIL  ${r.error.slice(0, 90)}`);
}
writeFileSync(`${HERE}measure.json`, JSON.stringify(res, null, 1));
