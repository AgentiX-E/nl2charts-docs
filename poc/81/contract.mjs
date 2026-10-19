// POC-81: connector contract — the assertions a PostgreSQL adapter must satisfy.
//
// Runs against two backends with the same assertion table:
//   PGlite (default)   PostgreSQL as WASM, CPU only, no daemon
//   real cluster       PG_DSN points at postgres://... on a runner service
//
// The split is not cosmetic. POC-79/81 established that the *semantic* layer is
// identical between the two, while the *connection* layer is where a server can
// differ — and in one case differs in the opposite direction (statement_timeout
// is enforced by a server and ignored under WASM).
//
// Every assertion is tagged:
//   universal  both backends must satisfy it
//   cluster    only a server can answer (auth, pool reuse, RLS)
// and classified by what a failure means:
//   gate       the adapter is wrong
//   obligation the *host* must do it (recorded, does not fail the run)
import { writeFileSync } from 'node:fs';

const outFile = process.argv[2] || '/tmp/contract.json';
const DSN = process.env.PG_DSN || '';
const results = [];

function record(id, cls, kind, expected, got, pass, note = '') {
  results.push({ id, class: cls, kind, expected, got, pass, note });
}

// ---------------------------------------------------------------- backends

class PgliteBackend {
  constructor(db) { this.kind = 'pglite'; this.db = db; }
  async exec(sql) { await this.db.exec(sql); }
  async query(sql) { const r = await this.db.query(sql); return r.rows; }
  async close() { await this.db.close(); }
}

class PgBackend {
  constructor(client, Pool) { this.kind = 'pg'; this.c = client; this.Pool = Pool; }
  async exec(sql) { await this.c.query(sql); }
  async query(sql) { const r = await this.c.query(sql); return r.rows; }
  async close() { await this.c.end(); }
}

async function connect() {
  if (!DSN) {
    const { PGlite } = await import('@electric-sql/pglite');
    const db = new PGlite();
    return new PgliteBackend(db);
  }
  const pg = await import('pg');
  const client = new pg.default.Client({ connectionString: DSN });
  await client.connect();
  return new PgBackend(client, pg.default.Pool);
}

async function expectError(db, sql) {
  try { await db.exec(sql); return false; } catch { return true; }
}

// ---------------------------------------------------------------- assertions

async function universal(db) {
  // 1 read-only transaction
  {
    await db.exec('CREATE TABLE IF NOT EXISTS t1 (a int)');
    await db.exec('BEGIN READ ONLY');
    const rejected = await expectError(db, 'INSERT INTO t1 VALUES (1)');
    await db.exec('ROLLBACK');
    record('readonly-transaction', 'universal', 'gate',
      'write rejected', rejected ? 'rejected' : 'accepted', rejected);
  }

  // 2 statement_timeout
  {
    await db.exec("SET statement_timeout = '100ms'");
    const t0 = Date.now();
    let aborted = false;
    try { await db.query('SELECT pg_sleep(0.6)'); } catch { aborted = true; }
    const ms = Date.now() - t0;
    await db.exec('SET statement_timeout = 0');
    record('statement-timeout', 'universal', 'obligation',
      'aborted near 100ms', `${aborted ? 'aborted' : 'completed'} in ${ms}ms`, aborted,
      aborted ? '' : 'WASM does not interrupt a running statement; the host must terminate the worker');
  }

  // 3 search_path
  {
    await db.exec('CREATE SCHEMA IF NOT EXISTS s2');
    await db.exec('CREATE TABLE IF NOT EXISTS s2.t3 (a int)');
    await db.exec('DELETE FROM s2.t3');
    await db.exec('INSERT INTO s2.t3 VALUES (7)');
    await db.exec("SET search_path = 's2'");
    const r = await db.query('SELECT a FROM t3');
    await db.exec("SET search_path = '$user', public");
    const ok = r.length === 1 && Number(r[0].a) === 7;
    record('search-path', 'universal', 'gate', 'resolves to s2.t3',
      ok ? 'resolved' : 'not resolved', ok,
      'a pooled session must reset this; it leaks between tenants otherwise');
  }

  // 4 rollback
  {
    await db.exec('CREATE TABLE IF NOT EXISTS t2 (a int)');
    await db.exec('BEGIN');
    await db.exec('INSERT INTO t2 VALUES (1)');
    await db.exec('ROLLBACK');
    const r = await db.query('SELECT count(*) AS n FROM t2');
    const ok = Number(r[0].n) === 0;
    record('transaction-rollback', 'universal', 'gate', '0 rows', `${r[0].n} rows`, ok);
  }

  // 5 identifier folding
  {
    await db.exec('DROP TABLE IF EXISTS "MiXeD"');
    await db.exec('CREATE TABLE "MiXeD" (a int)');
    const q = await db.query("SELECT count(*) AS n FROM information_schema.tables WHERE table_name = 'MiXeD'");
    const f = await db.query("SELECT count(*) AS n FROM information_schema.tables WHERE table_name = 'mixed'");
    const ok = Number(q[0].n) === 1 && Number(f[0].n) === 0;
    record('identifier-folding', 'universal', 'gate', 'quoted kept, unquoted folded',
      `quoted=${q[0].n} folded=${f[0].n}`, ok,
      'SQLite is case-insensitive; a table named "Users" changes meaning on PG');
  }

  // 6 boolean strictness
  {
    await db.exec('CREATE TABLE IF NOT EXISTS t5 (flag boolean)');
    await db.exec('DELETE FROM t5');
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
    const ok = r[0].v === null;
    record('concat-null', 'universal', 'gate', 'NULL', ok ? 'NULL' : String(r[0].v), ok);
  }

  // 8 collation: the one that changes a chart's axis order
  {
    await db.exec('CREATE TABLE IF NOT EXISTS t6 (s text)');
    await db.exec('DELETE FROM t6');
    await db.exec("INSERT INTO t6 VALUES ('a'), ('B'), ('c'), ('Á')");
    const def = (await db.query('SELECT s FROM t6 ORDER BY s ASC')).map((x) => x.s).join(',');
    const c = (await db.query('SELECT s FROM t6 ORDER BY s COLLATE "C" ASC')).map((x) => x.s).join(',');
    record('text-collation', 'universal', 'obligation', 'both orders recorded',
      `default=${def} | C=${c}`, true,
      def === c ? 'same order on this server' : 'default and C differ, so axis order depends on the server; pin COLLATE');
  }

  // 9 NULL ordering
  {
    await db.exec('CREATE TABLE IF NOT EXISTS t7 (a int)');
    await db.exec('DELETE FROM t7');
    await db.exec('INSERT INTO t7 VALUES (2), (NULL), (1)');
    const r = await db.query('SELECT a FROM t7 ORDER BY a ASC');
    record('null-ordering', 'universal', 'obligation', 'NULLS LAST (PG default)',
      r[0].a === null ? 'NULLS FIRST' : 'NULLS LAST', true,
      'differs from SQLite; a bar chart gains a phantom category');
  }
}

async function cluster(db) {
  if (db.kind !== 'pg') {
    for (const [id, note] of [
      ['tls-and-auth', "no network under WASM; auth is the pg driver's contract"],
      ['pool-reuse', 'no pool under WASM; a single process holds one session'],
      ['multi-tenant-rls', 'WASM runs as one superuser, so policies cannot be exercised'],
    ]) record(id, 'cluster', 'gap', 'see note', 'skipped', null, note);
    return;
  }

  // 10 connection identity: proves the DSN path (host/port/user/password) works
  {
    const r = await db.query('SELECT current_user, current_database(), version()');
    const ok = !!r[0].current_user;
    record('tls-and-auth', 'cluster', 'gate', 'authenticated session',
      `${r[0].current_user}@${r[0].current_database}`, ok,
      String(r[0].version).slice(0, 44));
  }

  // 11 pool reuse: does session state leak between checkouts?
  {
    const pool = new db.Pool({ connectionString: DSN, max: 1 });
    const c1 = await pool.connect();
    await c1.query("SET search_path = 's2'");
    c1.release();
    const c2 = await pool.connect();
    const r = await c2.query('SHOW search_path');
    c2.release();
    await pool.end();
    const leaked = String(r.rows[0].search_path).includes('s2');
    record('pool-reuse', 'cluster', 'obligation', 'no leak across checkouts',
      leaked ? 'leaked' : 'clean', !leaked,
      leaked ? 'pg.Pool does not reset session state; the adapter must RESET ALL on release' : '');
  }

  // 12 row-level security with a non-superuser role
  {
    let ok = false, got = '';
    try {
      await db.exec('DROP TABLE IF EXISTS rls_demo');
      await db.exec('CREATE TABLE rls_demo (tenant text, v int)');
      await db.exec("INSERT INTO rls_demo VALUES ('a', 1), ('b', 2)");
      await db.exec('ALTER TABLE rls_demo ENABLE ROW LEVEL SECURITY');
      await db.exec('DROP POLICY IF EXISTS p_tenant ON rls_demo');
      await db.exec("CREATE POLICY p_tenant ON rls_demo USING (tenant = current_setting('app.tenant', true))");
      await db.exec("SET app.tenant = 'a'");
      // superusers bypass RLS, so switch to an unprivileged role first
      await db.exec('DROP ROLE IF EXISTS app_user');
      await db.exec('CREATE ROLE app_user NOLOGIN');
      await db.exec('GRANT SELECT ON rls_demo TO app_user');
      await db.exec('SET ROLE app_user');
      const r = await db.query('SELECT tenant, v FROM rls_demo');
      await db.exec('RESET ROLE');
      ok = r.length === 1 && r[0].tenant === 'a';
      got = JSON.stringify(r);
    } catch (e) {
      got = String(e.message).slice(0, 80);
    }
    record('multi-tenant-rls', 'cluster', 'gate', 'only tenant a visible', got, ok,
      'the server filters rows; a client-side filter would be a different product');
  }
}

// ---------------------------------------------------------------- main

async function main() {
  const db = await connect();
  try {
    await universal(db);
    await cluster(db);
  } finally {
    await db.close().catch(() => {});
  }

  const gate = results.filter((r) => r.kind === 'gate');
  const obligations = results.filter((r) => r.kind === 'obligation');
  const summary = {
    backend: db.kind,
    assertions: results.length,
    gatesPassed: gate.filter((r) => r.pass).length,
    gatesFailed: gate.filter((r) => r.pass === false).length,
    obligations: obligations.length,
    obligationsUnmet: obligations.filter((r) => r.pass === false).length,
    skipped: results.filter((r) => r.pass === null).length,
  };
  // A gate is a bug; an unmet obligation is a requirement on the host.
  const ok = summary.gatesFailed === 0;
  writeFileSync(outFile, JSON.stringify({ ok, summary, assertions: results }, null, 1));
  console.log(JSON.stringify(summary));
  process.exit(ok ? 0 : 1);
}

main().catch((e) => { console.error(String(e.message || e)); process.exit(2); });
