// POC-43: does tree-shaking actually remove unused modules?
import * as esbuild from 'esbuild';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const out = {};
for (const [name, entry] of [['one-symbol', 'entry-one.js'], ['namespace', 'entry-all.js']]) {
  const r = await esbuild.build({
    entryPoints: [join(here, entry)], bundle: true, write: false,
    format: 'esm', minify: true, platform: 'browser', logLevel: 'silent',
  });
  out[name] = { bytes: Buffer.byteLength(r.outputFiles[0].text) };
}
out.ratio = Math.round(out.namespace.bytes / out['one-symbol'].bytes);
writeFileSync(join(here, 'shake.json'), JSON.stringify(out, null, 1));
console.log(JSON.stringify(out, null, 1));
