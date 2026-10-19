// POC-81: connector contract — what a PostgreSQL adapter must guarantee, and
// which guarantees PGlite cannot make for it.
//
// POC-79 proved PostgreSQL *semantics* can be tested without a server. It said
// nothing about the *connection*: read-only enforcement, statement timeouts,
// search_path, transaction scope, identifier folding, collation. Those live one
// layer below the SQL and decide whether a user's "read-only" query can write.
//
// Every assertion is tagged:
//   universal  any PostgreSQL server behaves this way; PGlite is a valid witness
//   cluster    only a real server can answer (auth, TLS, pooling, RLS)
// and classified by what a failure means:
//   gate       a failure means the adapter is wrong
//   obligation a failure means the *host* must do it instead of the server
//
// `obligation` is the interesting class. It is how "statement_timeout is not
// enforced under WASM" becomes a requirement on our code rather than a red build.
import { writeFileSync } from 'node:fs';
import { PGlite } from '@electric-sql/pglite';

const outFile = process.argv[2] || '/tmp/contract.json';
const results = [];

function record(id, cls, kind, expected, got, pass, note = '') {
  results.push({ id, class: cls, kind, expected, got, pass, note });
}

async function expectError(db, sql) {
  try { await db.exec(sql); return false; } catch { return true; }
}

async function main() {
  const db = new PGlite();

  // 1 read-only transaction
  {
    await db.exec('CREATE TABLE t1 (a int)');
    await db.exec('BEGIN READ ONLY');
    const rejected = await expectError(db, 'INSERT INTO t1 VALUES (1)');
    await db.exec('ROLLBACK');
    record('readonly-transaction', 'universal', 'gate',
      'write rejected', rejected ? 'rejected' : 'accepted', rejected);
  }

  // 2 statement_timeout: the server should abort, or the host must
  {
    await db.exec("SET statement_timeout = '100ms'");
    const t0 = Date.now();
    let aborted = false;
    try { await db.query('SELECT pg_sleep(0.6)'); } catch { aborted = true; }
    const ms = Date.now() - t0;
    await db.exec('SET statement_timeout = 0');
    record('statement-timeout', 'universal', 'obligation',
      'aborted near 100ms', `${aborted ? 'aborted' : 'completed'} in ${ms}ms`, aborted,
      aborted ? '' : 'PGlite ignores statement_timeout; the host must enforce a deadline (worker termination) or a slow query pins the tab');
  }

  // 3 search_path
  {
    await db.exec('CREATE SCHEMA s2');
    await db.exec('CREATE TABLE s2.t3 (a int)');
    await db.exec('INSERT INTO s2.t3 VALUES (7)');
    await db.exec("SET search_path = 's2'");
    const r = await db.query('SELECT a FROM t3');
    const ok = r.rows.length === 1 && Number(r.rows[0].a) === 7;
    record('search-path', 'universal', 'gate', 'resolves to s2.t3',
      ok ? 'resolved' : 'not resolved', ok,
      'a pooled session must reset this; it leaks between tenants otherwise');
  }

  // 4 rollback
  {
    await db.exec('CREATE TABLE t2 (a int)');
    await db.exec('BEGIN');
    await db.exec('INSERT INTO t2 VALUES (1)');
    await db.exec('ROLLBACK');
    const r = await db.query('SELECT count(*) AS n FROM t2');
    const ok = Number(r.rows[0].n) === 0;
    record('transaction-rollback', 'universal', 'gate', '0 rows', `${r.rows[0].n} rows`, ok);
  }

  // 5 identifier folding
  {
    await db.exec('CREATE TABLE "MiXeD" (a int)');
    const q = await db.query("SELECT count(*) AS n FROM information_schema.tables WHERE table_name = 'MiXeD'");
    const f = await db.query("SELECT count(*) AS n FROM information_schema.tables WHERE table_name = 'mixed'");
    const ok = Number(q.rows[0].n) === 1 && Number(f.rows[0].n) === 0;
    record('identifier-folding', 'universal', 'gate', 'quoted kept, unquoted folded',
      `quoted=${q.rows[0].n} folded=${f.rows[0].n}`, ok,
      'SQLite is case-insensitive; a table named "Users" changes meaning on PG');
  }

  // 6 boolean strictness
  {
    await db.exec('CREATE TABLE t5 (flag boolean)');
    await db.exec('INSERT INTO t5 VALUES (TRUE)');
    let rejected = false;
    try { await db.query('SELECT * FROM t5 WHERE flag = 1'); } catch { rejected = true; }
    record('boolean-strictness', 'universal', 'gate', 'flag = 1 rejected',
      rejected ? 'rejected' : 'accepted', rejected,
      'generated SQL often compares booleans to 1, which SQLite accepts');
  }

  // 7 NULL propagation
  {
    const r = await db.query("SELECT ('a' || NULL) AS v");
    const ok = r.rows[0].v === null;
    record('concat-null', 'universal', 'gate', 'NULL', ok ? 'NULL' : String(r.rows[0].v), ok);
  }

  // 8 collation: the one that changes a chart's axis order
  {
    await db.exec('CREATE TABLE t6 (s text)');
    await db.exec("INSERT INTO t6 VALUES ('a'), ('B'), ('c'), ('Á')");
    const r = await db.query('SELECT s FROM t6 ORDER BY s ASC');
    const order = r.rows.map((x) => x.s).join(',');
    // SQLite BINARY would give 'B','a','c','Á'; a case-insensitive collation
    // gives 'a','Á','B','c'. Which one appears decides what the x-axis looks like.
    record('text-collation', 'universal', 'obligation', 'order recorded',
      order, true,
      'PGlite defaults to C (byte order); a cluster initdb-ed with en_US.UTF-8 ' +
      'orders a,Á,B,c instead, so the axis order differs by *server*, which no ' +
      'client-side test can see. The adapter must pin COLLATE explicitly');
  }

  // 9 NULL ordering
  {
    await db.exec('CREATE TABLE t7 (a int)');
    await db.exec('INSERT INTO t7 VALUES (2), (NULL), (1)');
    const r = await db.query('SELECT a FROM t7 ORDER BY a ASC');
    record('null-ordering', 'universal', 'obligation', 'NULLS LAST (PG default)',
      r.rows[0].a === null ? 'NULLS FIRST' : 'NULLS LAST', true,
      'differs from SQLite; a bar chart gains a phantom category');
  }

  // ---- cluster-only: named, never silently skipped ----
  record('tls-and-auth', 'cluster', 'gap', 'TLS + SCRAM', 'skipped', null,
    'PGlite has no network; auth is the pg driver\'s contract, not ours');
  record('pool-reuse', 'cluster', 'gap', 'no session state leak across checkouts', 'skipped', null,
    'requires a real pool; search_path and statement_timeout are per-session');
  record('multi-tenant-rls', 'cluster', 'gap', 'RLS enforced by roles', 'skipped', null,
    'PGlite runs as one superuser, so policies cannot be exercised');

  await db.close();

  const universal = results.filter((r) => r.class === 'universal');
  const gate = universal.filter((r) => r.kind === 'gate');
  const obligations = universal.filter((r) => r.kind === 'obligation');
  const summary = {
    universal: universal.length,
    gatesPassed: gate.filter((r) => r.pass).length,
    gatesFailed: gate.filter((r) => r.pass === false).length,
    obligations: obligations.length,
    obligationsUnmet: obligations.filter((r) => r.pass === false).length,
    clusterSkipped: results.filter((r) => r.class === 'cluster').length,
  };
  // A gate failure is a bug; an unmet obligation is a requirement on the host.
  const ok = summary.gatesFailed === 0;
  writeFileSync(outFile, JSON.stringify({ ok, summary, assertions: results }, null, 1));
  console.log(JSON.stringify(summary));
  process.exit(ok ? 0 : 1);
}

main().catch((e) => { console.error(String(e.message || e)); process.exit(2); });
