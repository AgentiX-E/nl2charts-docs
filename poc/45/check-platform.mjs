#!/usr/bin/env node
/**
 * tools/check-platform.mjs -- platform boundary gates (PLT1-PLT6).
 * Exit 0 only when every gate passes; each violation is printed with its id.
 */
import * as esbuild from 'esbuild';
import { readFileSync, existsSync, readdirSync, copyFileSync, mkdirSync, rmSync } from 'node:fs';
import { join, dirname, resolve, basename } from 'node:path';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
const pkgDir = resolve(args[args.indexOf('--packages') + 1] ?? 'packages');
const DRIVERS = /(^|\/)(pg|mysql2|@duckdb\/node-api|@duckdb\/duckdb-wasm|better-sqlite3)$/;
const NODE_BUILTIN = /node:(fs|net|tls|dns|http2|child_process|crypto|os)/;
const ORCHESTRATION = /\b(createAgent|askStream|createAdminHandler)\b/;
const violations = [];

const pkgs = readdirSync(pkgDir, { withFileTypes: true })
  .filter((d) => d.isDirectory() && existsSync(join(pkgDir, d.name, 'package.json')))
  .map((d) => {
    const dir = join(pkgDir, d.name);
    const pj = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'));
    return { dir, name: d.name, pkg: pj };
  });

const corePkgs = pkgs.filter((p) => p.name === 'core');
const platformPkgs = pkgs.filter((p) => p.name === 'node' || p.name === 'browser');

const entryOf = (p) => {
  const e = p.pkg.exports?.['.'];
  const path = typeof e === 'string' ? e : e?.default ?? e?.import;
  return path ? join(p.dir, path) : null;
};

// ---- PLT1/PLT2: what a browser build of the root entry actually pulls in ----
async function bundleForBrowser(entry) {
  try {
    const out = await esbuild.build({
      entryPoints: [entry], bundle: true, write: false, platform: 'browser',
      format: 'esm', minify: true, logLevel: 'silent', target: 'es2020', metafile: true,
      external: ['zod', 'ai', 'pg', 'mysql2', '@duckdb/*', 'better-sqlite3', 'node:*'],
    });
    const code = out.outputFiles[0].text;
    const meta = Object.values(out.metafile.outputs)[0];
    return { ok: true, code, imports: meta.imports.map((i) => i.path) };
  } catch (e) {
    return { ok: false, error: String(e.message).split('\n').slice(0, 2).join(' | ') };
  }
}

for (const p of corePkgs) {
  const entry = entryOf(p);
  const r = entry ? await bundleForBrowser(entry) : { ok: false, error: 'no "." export' };
  if (!r.ok) {
    violations.push(['PLT1', p.name, `root entry cannot be bundled for browser: ${r.error}`]);
    continue;
  }
  const builtin = r.code.match(NODE_BUILTIN);
  if (builtin) violations.push(['PLT1', p.name, `browser bundle contains ${builtin[0]}`]);
  const bad = r.imports.filter((i) => DRIVERS.test(i));
  for (const b of bad) violations.push(['PLT2', p.name, `root entry imports platform-only module "${b}"`]);
}

// ---- PLT3: public type surface must not name a platform-only module ----
const typeFilesOf = (p) => {
  const out = [];
  for (const [sub, val] of Object.entries(p.pkg.exports ?? {})) {
    const types = typeof val === 'object' ? val.types : null;
    if (types) out.push({ sub, file: join(p.dir, types) });
  }
  return out;
};
const NODE_ONLY_SUB = /duckdb-node|connectors\/(pg|mysql|s3|file)|node/;
for (const p of pkgs) {
  for (const t of typeFilesOf(p)) {
    if (!existsSync(t.file)) continue;
    if (NODE_ONLY_SUB.test(t.sub)) continue;          // node-only subpaths may import node types
    const src = readFileSync(t.file, 'utf8');
    for (const m of src.matchAll(/from\s+['"]([^'"]+)['"]/g)) {
      const spec = m[1];
      if (DRIVERS.test(spec) || spec.startsWith('node:')) {
        violations.push(['PLT3', `${p.name}${t.sub === '.' ? '' : '/' + t.sub}`, `public types reference "${spec}"`]);
      }
    }
  }
}

// ---- PLT4: dependency direction ----
for (const p of pkgs) {
  const deps = { ...(p.pkg.dependencies ?? {}), ...(p.pkg.peerDependencies ?? {}) };
  const targets = Object.keys(deps).filter((k) => k.includes('nl2charts-'));
  if (p.name === 'core') {
    for (const t of targets) {
      if (/-node$|-browser$/.test(t)) violations.push(['PLT4', p.name, `core must not depend on platform package ${t}`]);
    }
  }
  if (p.name === 'node' && targets.some((t) => /-browser$/.test(t)))
    violations.push(['PLT4', p.name, 'node must not depend on browser package']);
  if (p.name === 'browser' && targets.some((t) => /-node$/.test(t)))
    violations.push(['PLT4', p.name, 'browser must not depend on node package']);
}

// ---- PLT5: platform packages carry bindings only, never orchestration ----
for (const p of platformPkgs) {
  const entry = entryOf(p);
  if (!entry || !existsSync(entry)) continue;
  const src = readFileSync(entry, 'utf8');
  const hit = src.match(ORCHESTRATION);
  if (hit) violations.push(['PLT5', p.name, `platform package exports orchestration symbol "${hit[0]}"`]);
}

// ---- PLT6: cross-copy identity must survive (brand + registry) ----
const tmp = join(pkgDir, '..', '.plt6');

// driver modules are irrelevant to identity checks; stub them so the probe
// does not depend on whether the host happens to have installed a driver
const stubDrivers = {
  name: 'stub-drivers',
  setup(build) {
    build.onResolve({ filter: /^(pg|mysql2|better-sqlite3|@duckdb\/.*)$/ }, (a) => ({ path: a.path, namespace: 'stub' }));
    build.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({
      contents: 'export default {}; export class Client { constructor(){} } export const connect = () => {};',
      loader: 'js',
    }));
  },
};

async function buildCopy(entry, outfile) {
  mkdirSync(dirname(outfile), { recursive: true });
  const r = await esbuild.build({
    entryPoints: [entry], bundle: true, write: true, outfile,
    platform: 'node', format: 'esm', logLevel: 'silent', target: 'node20',
    external: ['zod', 'ai'], plugins: [stubDrivers],
  });
  return r;
}

if (corePkgs.length === 1) {
  const core = corePkgs[0];
  const entry = entryOf(core);
  const abs = entry ? resolve(core.dir, entry) : null;
  if (abs && existsSync(abs)) {
    rmSync(tmp, { recursive: true, force: true });
    try {
      const A = join(tmp, 'a', 'core.mjs');
      const B = join(tmp, 'b', 'core.mjs');
      await buildCopy(abs, A);
      await buildCopy(abs, B);
      const modA = await import(pathToFileURL(A).href + '?v=a');
      const modB = await import(pathToFileURL(B).href + '?v=b');

      // (1) brand carried by a foreign copy must be recognised by both
      if (typeof modA.isEngine === 'function') {
        const brand = modA.ENGINE_BRAND ?? Symbol.for('nl2charts.engine');
        const foreign = { kind: 'x', query: async () => [], close: async () => {}, [brand]: true };
        if (modA.isEngine(foreign) !== true) violations.push(['PLT6', core.name, 'copy A rejects an object carrying the registered brand']);
        if (modB.isEngine(foreign) !== true) violations.push(['PLT6', core.name, 'copy B rejects an object carrying the registered brand']);
      }
      // (2) registry must be process-wide, not per-copy
      if (typeof modA.register === 'function' && typeof modB.resolve === 'function') {
        modB.register('plt-probe', () => 'ok');
        if (modA.resolve('plt-probe') === null) violations.push(['PLT6', core.name, 'registry does not span copies (module-level state)']);
      }
      // (3) static guards
      const src = readFileSync(abs, 'utf8');
      if (/instanceof\s+\w*Engine/.test(src)) violations.push(['PLT6', core.name, 'uses instanceof for engine detection (breaks across copies)']);
      if (/new Map\(\)/.test(src) && !/globalThis/.test(src)) violations.push(['PLT6', core.name, 'module-level Map registry (splits across copies)']);
    } catch (e) {
      violations.push(['PLT6', core.name, `dual-copy check failed: ${String(e.message).slice(0, 90)}`]);
    }
  }
}

const report = {
  packages: pkgs.map((p) => p.name),
  gates: ['PLT1', 'PLT2', 'PLT3', 'PLT4', 'PLT5', 'PLT6'],
  violations: violations.map(([id, pkg, msg]) => ({ id, pkg, msg })),
};
console.log(JSON.stringify(report, null, 1));
if (violations.length) { console.error(`FAIL: ${violations.length} violation(s)`); process.exit(1); }
console.error('PASS: all platform gates green');
