// POC-79, step 2: run a job list against PGlite (PostgreSQL as WASM, CPU only).
//
// Node has no SQLite driver here on purpose: the comparison is "same question,
// same expected rows, different engine", and loading through a common JSON dump
// keeps the two sides from sharing a parser.
//
// PGlite returns bigint and numeric as strings. That is not a detail to hide —
// it is the third-engine version of POC-78's type mismatch, so rows are emitted
// exactly as the engine produced them and normalised on the Python side.
import { readFileSync, writeFileSync } from 'node:fs';
import { PGlite } from '@electric-sql/pglite';

const [, , jobFile, outFile] = process.argv;
const spec = JSON.parse(readFileSync(jobFile, 'utf8'));

function lit(v) {
  if (v === null || v === undefined) return 'NULL';
  if (typeof v === 'number') return Number.isFinite(v) ? String(v) : 'NULL';
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  return "'" + String(v).replace(/'/g, "''") + "'";
}

async function loadDb(db, dumpPath) {
  const d = JSON.parse(readFileSync(dumpPath, 'utf8'));
  for (const [table, body] of Object.entries(d.tables)) {
    const cols = body.columns.map((c) => `"${c.name}" ${c.pg}`).join(', ');
    await db.exec(`CREATE TABLE "${table}" (${cols})`);
    const rows = body.rows;
    if (!rows.length) continue;
    const width = body.columns.length;
    // Chunked multi-row INSERT: one statement per row is 50x slower and 50x
    // more memory churn for a 50k-row table.
    const chunk = 500;
    for (let i = 0; i < rows.length; i += chunk) {
      const part = rows.slice(i, i + chunk)
        .map((r) => '(' + Array.from({ length: width }, (_, k) => lit(r[k])).join(',') + ')')
        .join(',');
      await db.exec(`INSERT INTO "${table}" VALUES ${part}`);
    }
  }
  return Object.keys(d.tables).length;
}

const results = { jobs: [], dbs: {} };
const cache = new Map();

for (const job of spec.jobs) {
  let db = cache.get(job.db);
  if (!db) {
    const t0 = Date.now();
    db = new PGlite();
    const tables = await loadDb(db, spec.dumps[job.db]);
    results.dbs[job.db] = { tables, loadMs: Date.now() - t0 };
    cache.set(job.db, db);
    if (spec.onlyLoad) continue;
  }
  const rec = { id: job.id, db: job.db, tag: job.tag };
  try {
    const r = await db.query(job.sql);
    rec.ok = true;
    rec.ncols = r.fields.length;
    // Rows are objects keyed by column name; the comparator needs positional
    // tuples, and PG does not preserve duplicate projection names in objects.
    rec.rows = r.rows.map((o) => Object.values(o));
  } catch (e) {
    rec.ok = false;
    rec.error = String(e.message || e).slice(0, 200);
  }
  results.jobs.push(rec);
}

for (const db of cache.values()) await db.close();
writeFileSync(outFile, JSON.stringify(results));
console.log(JSON.stringify({
  dbs: results.dbs,
  jobs: results.jobs.length,
  ok: results.jobs.filter((j) => j.ok).length,
}));
