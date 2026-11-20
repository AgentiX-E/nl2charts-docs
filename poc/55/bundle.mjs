import { build } from 'esbuild';
import zlib from 'node:zlib';
import fs from 'node:fs';
const r = await build({
  entryPoints: ['entry.mjs'], bundle: true, format: 'esm', minify: true,
  platform: 'neutral', write: false, metafile: true,
  external: ['node:crypto', 'node:fs'],
});
const out = r.outputFiles[0].contents;
const text = out.toString('utf8');
const imports = Object.keys(r.metafile.inputs);
const res = {
  bytes: out.length,
  gzip: zlib.gzipSync(out).length,
  inputs: imports,
  importsCore: imports.filter(p => /core|ai\//.test(p)),
  importsChart: imports.filter(p => /chart/.test(p)),
  hasAiSdk: /@ai-sdk|from ['"]ai['"]/.test(text),
  hasNodeBuiltin: /node:(fs|http|net|worker_threads)/.test(text),
};
fs.writeFileSync('bundle.json', JSON.stringify(res, null, 2));
console.log(JSON.stringify(res, null, 2));
