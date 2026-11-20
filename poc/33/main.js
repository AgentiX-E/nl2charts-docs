/**
 * POC-33: SQL 守卫对抗测试 + 误杀率
 * 守卫策略（ADR-071）：
 *  G1 解析失败 => 拒绝
 *  G2 BASE_TABLE：catalog 必须在白名单；两段名且 schema 命中已挂载 catalog => 拒绝（AMBIGUOUS）
 *  G3 TABLE_FUNCTION：只放行 range/generate_series/unnest
 *  G4 语句类型：只允许 SELECT/WITH（含集合运算），其它 node type 直接拒绝
 */
const { DuckDBInstance } = require('@duckdb/node-api');

const ALLOW_CATALOGS = new Set(['memory', 'main']);          // 只允许本地
const ALLOW_TABLE_FNS = new Set(['range', 'generate_series', 'unnest']);
const ALLOW_TOP_TYPES = new Set(['SELECT_NODE', 'SET_OPERATION_NODE', 'RECURSIVE_CTE_NODE']);

const lit = (s) => "'" + s.replaceAll("'", "''") + "'";

// 合法查询（必须放行）
const LEGIT = [
  ['sel1', `SELECT region, sum(amount) v FROM orders WHERE status='paid' GROUP BY 1`],
  ['sel2', `WITH a AS (SELECT 1 x) SELECT * FROM a`],
  ['sel3', `SELECT * FROM main.orders LIMIT 5`],
  ['sel4', `SELECT count(*) FROM orders o JOIN items i USING(order_id)`],
  ['sel5', `SELECT * FROM range(10)`],
  ['sel6', `SELECT * FROM generate_series(1,5)`],
  ['sel7', `SELECT unnest([1,2,3])`],
  ['sel8', `SELECT 1 UNION ALL SELECT 2`],
  ['sel9', `SELECT * FROM orders WHERE region IN (SELECT region FROM orders WHERE amount>100)`],
  ['sel10', `SELECT row_number() OVER (PARTITION BY region ORDER BY amount) rn, * FROM orders`],
  ['sel11', `SELECT CASE WHEN 1=1 THEN 'a' ELSE 'b' END`],
  ['sel12', `SELECT strftime(DATE '2026-01-01','%Y-%m')`],
  ['sel13', `SELECT * FROM (VALUES (1),(2)) t(x)`],
  ['sel14', `SELECT list_transform([1,2], x -> x+1)`],
  ['sel15', `SELECT * FROM orders WHERE amount BETWEEN 10 AND 20`],
  ['sel16', `SELECT region, count(*) FROM orders GROUP BY ALL HAVING count(*)>1`],
  ['sel17', `SELECT * FROM orders QUALIFY row_number() OVER () = 1`],
  ['sel18', `SELECT * FROM orders o SEMI JOIN items i USING(order_id)`] ,
  ['sel19', `SELECT * FROM orders PIVOT (sum(amount) FOR region IN ('华东','华北'))`],
  ['sel20', `SELECT 1 AS "金额", '中文' AS "地区"`],
  ['sel21', `SELECT * FROM orders o LEFT JOIN items i ON o.order_id=i.order_id`],
  ['sel22', `SELECT * FROM (SELECT 1 a) t WHERE a > 0`],
  ['sel23', `SELECT sum(amount) FILTER (WHERE status='paid') FROM orders`],
  ['sel24', `SELECT * FROM orders TABLESAMPLE 10 PERCENT`],
  ['sel25', `SELECT * FROM main.orders o, main.items i WHERE o.order_id=i.order_id`],
];

// 攻击（必须拒绝）
const ATTACKS = [
  ['file_read_csv', `SELECT * FROM read_csv('/etc/passwd')`, 'file_read'],
  ['file_read_parquet', `SELECT * FROM read_parquet('/etc/shadow')`, 'file_read'],
  ['file_glob', `SELECT * FROM glob('/*')`, 'file_read'],
  ['sys_settings', `SELECT * FROM duckdb_settings()`, 'system'],
  ['sys_functions', `SELECT * FROM duckdb_functions()`, 'system'],
  ['sys_tables', `SELECT * FROM duckdb_tables()`, 'system'],
  ['sys_databases', `SELECT * FROM duckdb_databases()`, 'system'],
  ['pragma', `PRAGMA database_list`, 'statement'],
  ['attach', `ATTACH '/tmp/evil.db' AS evil`, 'statement'],
  ['copy_to', `COPY (SELECT 1) TO '/tmp/out.csv'`, 'statement'],
  ['copy_from', `COPY orders FROM '/etc/passwd'`, 'statement'],
  ['install', `INSTALL httpfs`, 'statement'],
  ['load', `LOAD httpfs`, 'statement'],
  ['set_var', `SET memory_limit='1GB'`, 'statement'],
  ['create', `CREATE TABLE evil(x INT)`, 'statement'],
  ['insert', `INSERT INTO orders VALUES (1)`, 'statement'],
  ['update', `UPDATE orders SET amount=0`, 'statement'],
  ['delete', `DELETE FROM orders`, 'statement'],
  ['drop', `DROP TABLE orders`, 'statement'],
  ['export', `EXPORT DATABASE '/tmp/dump'`, 'statement'],
  ['two_part_bypass', `SELECT * FROM evil.orders`, 'catalog_bypass'],
  ['three_part_other', `SELECT * FROM other.main.orders`, 'catalog_bypass'],
  ['stacked', `SELECT 1; DROP TABLE orders`, 'statement'],
  ['comment_inject', `SELECT 1 /* x */ ; ATTACH '/tmp/x.db' AS x`, 'statement'],
  ['union_smuggle', `SELECT 1 UNION ALL SELECT count(*) FROM read_csv('/etc/passwd')`, 'file_read'],
  ['subquery_smuggle', `SELECT * FROM (SELECT * FROM duckdb_settings())`, 'system'],
  ['table_fn_nested', `SELECT * FROM (SELECT * FROM read_csv('/etc/passwd'))`, 'file_read'],
  ['recursive_bomb', `WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM r) SELECT count(*) FROM r`, 'resource'],
];

// ---------- 守卫 ----------
function walk(node, cb) {
  if (!node || typeof node !== 'object') return;
  cb(node);
  for (const k of Object.keys(node)) walk(node[k], cb);
}

function createGuard(conn) {
  return async function check(sql) {
    const reasons = [];
    // G1 解析
    let tree;
    try {
      const r = await conn.runAndReadAll(`SELECT json_serialize_sql(${lit(sql)})`);
      const j = JSON.parse(r.getRows()[0][0]);
      if (j.error) return { allow: false, code: 'PARSE_ERROR', detail: String(j.error_message || '').slice(0, 60) };
      tree = j;
    } catch (e) {
      return { allow: false, code: 'PARSE_ERROR', detail: String(e.message).slice(0, 60) };
    }

    // G4 语句类型：stmt 顶层 node.type
    const stmts = tree.statements || [];
    if (stmts.length !== 1) return { allow: false, code: 'STATEMENT_NOT_ALLOWED', detail: `statements=${stmts.length}` };
    const topType = stmts[0]?.node?.type;
    if (!ALLOW_TOP_TYPES.has(topType) && topType !== 'SELECT_NODE') {
      return { allow: false, code: 'STATEMENT_NOT_ALLOWED', detail: `type=${topType}` };
    }

    // G2 / G3
    let denied = null;
    walk(tree, (n) => {
      if (denied) return;
      if (n.type === 'BASE_TABLE') {
        const cat = n.catalog_name || '';
        const sch = n.schema_name || '';
        if (cat) {
          if (!ALLOW_CATALOGS.has(cat)) denied = { allow: false, code: 'CATALOG_NOT_ALLOWED', detail: cat };
        } else if (sch) {
          // 两段名：schema 位置可能是 catalog（POC-13 的绕过）
          if (!['main'].includes(sch) && !['main'].includes(sch.toLowerCase())) {
            denied = { allow: false, code: 'AMBIGUOUS_CATALOG_QUALIFIER', detail: `schema=${sch}` };
          }
        }
      }
      if (n.type === 'TABLE_FUNCTION') {
        const fn = n.function?.function_name || n.function_name || '';
        if (!ALLOW_TABLE_FNS.has(fn)) denied = { allow: false, code: 'TABLE_FUNCTION_NOT_ALLOWED', detail: fn };
      }
      if (n.type === 'BASE_TABLE' && n.function) {
        const fn = n.function.function_name || '';
        if (!ALLOW_TABLE_FNS.has(fn)) denied = { allow: false, code: 'TABLE_FUNCTION_NOT_ALLOWED', detail: fn };
      }
    });
    if (denied) return denied;
    return { allow: true, code: 'OK', detail: reasons.join(',') };
  };
}

(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const conn = await inst.connect();
  await conn.run(`CREATE TABLE orders(order_id BIGINT, region VARCHAR, amount DECIMAL(12,2), status VARCHAR)`);
  await conn.run(`INSERT INTO orders VALUES (1,'华东',10,'paid'),(2,'华北',20,'paid')`);
  await conn.run(`CREATE TABLE items(order_id BIGINT, product_id INT)`);
  await conn.run(`INSERT INTO items VALUES (1,1),(2,2)`);
  const guard = createGuard(conn);

  const rows = [];
  for (const [id, sql] of LEGIT) {
    const r = await guard(sql);
    rows.push({ id, kind: 'legit', sql, ...r });
  }
  for (const [id, sql, cat] of ATTACKS) {
    const r = await guard(sql);
    rows.push({ id, kind: 'attack', cat, sql, ...r });
  }

  const legit = rows.filter(r => r.kind === 'legit');
  const atk = rows.filter(r => r.kind === 'attack');
  const tp = atk.filter(r => !r.allow).length, fn = atk.length - tp;
  const fp = legit.filter(r => !r.allow).length, tn = legit.length - fp;

  const byCode = {};
  for (const r of atk) if (!r.allow) byCode[r.code] = (byCode[r.code] || 0) + 1;

  const out = {
    legit: { n: legit.length, passed: tn, blocked: fp },
    attack: { n: atk.length, blocked: tp, passed: fn },
    TPR: +(tp / atk.length).toFixed(3), FPR: +(fp / legit.length).toFixed(3),
    precision: +(tp / Math.max(tp + fp, 1)).toFixed(3),
    codes: byCode,
    legit_failures: legit.filter(r => !r.allow),
    attack_passes: atk.filter(r => r.allow),
    rows,
  };
  require('fs').writeFileSync('/tmp/poc33_results.json', JSON.stringify(out, null, 1));
  console.log(JSON.stringify({ legit: out.legit, attack: out.attack, TPR: out.TPR, FPR: out.FPR,
    precision: out.precision, codes: out.codes, legit_failures: out.legit_failures,
    attack_passes: out.attack_passes }, null, 1));
})().catch(e => { console.error('FATAL', e); process.exit(1); });
