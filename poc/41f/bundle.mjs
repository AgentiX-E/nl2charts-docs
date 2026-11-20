// POC-41: does one package keep a clean Node/browser boundary?
import * as esbuild from 'esbuild';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const alias = {
  '@agentix-e/nl2charts-core': join(here, 'pkg/src/index.js'),
  '@agentix-e/nl2charts-core/pg': join(here, 'pkg/src/connectors/pg.js'),
};
const cases = [
  ['browser-core-only', 'entry-a.js', 'browser'],
  ['browser-core-plus-pg', 'entry-b.js', 'browser'],
  ['node-core-plus-pg', 'entry-b.js', 'node'],
];
const res = {};
for (const [name, entry, platform] of cases) {
  try {
    const out = await esbuild.build({
      entryPoints: [join(here, entry)], bundle: true, write: false, platform, format: 'esm',
      minify: true, alias, logLevel: 'silent', target: platform === 'browser' ? 'es2020' : 'node20',
    });
    const code = out.outputFiles[0].text;
    res[name] = {
      ok: true, bytes: Buffer.byteLength(code),
      hasPg: /pg-pool|pg-protocol|new pg\.Client/.test(code),
      hasNodeBuiltin: /node:(fs|net|tls|dns)/.test(code),
    };
  } catch (e) {
    res[name] = { ok: false, error: String(e.message).split('\n').slice(0, 3).join(' | ') };
  }
}
writeFileSync(join(here, 'bundle.json'), JSON.stringify(res, null, 1));
console.log(JSON.stringify(res, null, 1));
