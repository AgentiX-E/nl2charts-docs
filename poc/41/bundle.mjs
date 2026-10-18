import * as esbuild from 'esbuild';
import { statSync, writeFileSync } from 'node:fs';
const alias = { '@agentix-e/nl2charts-core': '/tmp/poc41/pkg/src/index.js',
                '@agentix-e/nl2charts-core/pg': '/tmp/poc41/pkg/src/connectors/pg.js' };
const cases = [
  ['browser-core-only', 'entry-a.js', 'browser'],
  ['browser-core-plus-pg', 'entry-b.js', 'browser'],
  ['node-core-plus-pg', 'entry-b.js', 'node'],
];
const res = {};
for (const [name, entry, platform] of cases) {
  try {
    const out = await esbuild.build({
      entryPoints: [entry], bundle: true, write: false, platform, format: 'esm',
      minify: true, alias, logLevel: 'silent', target: platform === 'browser' ? 'es2020' : 'node20',
    });
    const code = out.outputFiles[0].text;
    res[name] = { ok: true, bytes: Buffer.byteLength(code),
      hasPg: /node_modules\/pg|pg-pool|new pg\.Client/.test(code),
      hasNodeBuiltin: /node:(fs|net|tls|dns)|require\("net"\)/.test(code) };
  } catch (e) {
    res[name] = { ok: false, error: String(e.message).split('\n').slice(0, 3).join(' | ') };
  }
}
writeFileSync('bundle.json', JSON.stringify(res, null, 1));
console.log(JSON.stringify(res, null, 1));
