const { DuckDBInstance } = require('@duckdb/node-api');
const lit = (s) => "'" + s.replaceAll("'", "''") + "'";
const ALLOW_CATALOGS = new Set(['memory', 'main']);
const ALLOW_TABLE_FNS = new Set(['range', 'generate_series', 'unnest']);
const ALLOW_FIRST = /^\s*(\(|select|with|values|from)\b/i;   // G0

function walk(n, cb){ if(!n||typeof n!=='object')return; cb(n); for(const k of Object.keys(n)) walk(n[k],cb); }

function createGuard(conn) {
  return async function check(sql) {
    // G0 关键字前筛：DDL/DML/管理语句在解析前即拒绝（可与语法错误区分）
    if (!ALLOW_FIRST.test(sql)) return { allow:false, code:'STATEMENT_NOT_ALLOWED', stage:'G0' };
    let tree;
    try {
      const r = await conn.runAndReadAll(`SELECT json_serialize_sql(${lit(sql)})`);
      const j = JSON.parse(r.getRows()[0][0]);
      if (j.error) return { allow:false, code:'PARSE_ERROR', stage:'G1', detail:String(j.error_message||'').slice(0,50) };
      tree = j;
    } catch (e) { return { allow:false, code:'PARSE_ERROR', stage:'G1', detail:String(e.message).slice(0,50) }; }
    const stmts = tree.statements || [];
    if (stmts.length !== 1) return { allow:false, code:'STATEMENT_NOT_ALLOWED', stage:'G4' };
    let denied = null;
    walk(tree, (n) => {
      if (denied) return;
      if (n.type === 'BASE_TABLE') {
        const cat = n.catalog_name || '', sch = n.schema_name || '';
        if (cat && !ALLOW_CATALOGS.has(cat)) denied = { allow:false, code:'CATALOG_NOT_ALLOWED', stage:'G2', detail:cat };
        else if (!cat && sch && sch.toLowerCase() !== 'main') denied = { allow:false, code:'AMBIGUOUS_CATALOG_QUALIFIER', stage:'G2', detail:sch };
      }
      if (n.type === 'TABLE_FUNCTION') {
        const fn = n.function?.function_name || n.function_name || '';
        if (!ALLOW_TABLE_FNS.has(fn)) denied = { allow:false, code:'TABLE_FUNCTION_NOT_ALLOWED', stage:'G3', detail:fn };
      }
    });
    return denied || { allow:true, code:'OK', stage:'-' };
  };
}

const { LEGIT, ATTACKS } = require('/tmp/poc33/cases.js');

(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const conn = await inst.connect();
  await conn.run(`CREATE TABLE orders(order_id BIGINT, region VARCHAR, amount DECIMAL(12,2), status VARCHAR)`);
  await conn.run(`INSERT INTO orders VALUES (1,'华东',10,'paid'),(2,'华北',20,'paid')`);
  await conn.run(`CREATE TABLE items(order_id BIGINT, product_id INT)`);
  await conn.run(`INSERT INTO items VALUES (1,1),(2,2)`);
  const guard = createGuard(conn);

  const rows = [];
  for (const [id, sql] of LEGIT) rows.push({ id, kind:'legit', sql, ...(await guard(sql)) });
  for (const [id, sql, cat] of ATTACKS) rows.push({ id, kind:'attack', cat, sql, ...(await guard(sql)) });

  // G5 资源守卫：800ms 超时 + interrupt
  const bomb = ATTACKS.find(a => a[0] === 'recursive_bomb')[1];
  let g5;
  const t0 = Date.now();
  try {
    const p = conn.run(bomb);
    const timer = setTimeout(() => { try { conn.interrupt(); } catch {} }, 800);
    await p; clearTimeout(timer);
    g5 = { cancelled:false, ms: Date.now()-t0 };
  } catch (e) { g5 = { cancelled:true, ms: Date.now()-t0, err:String(e.message).slice(0,80) }; }

  // 合法查询在 G5 下不受影响（取 25 条的执行耗时 p95）
  const lat = [];
  const c2 = await inst.connect();
  for (const [id, sql] of LEGIT) {
    const t = Date.now();
    try { await c2.runAndReadAll(sql); } catch {}
    lat.push(Date.now() - t);
  }
  lat.sort((a,b)=>a-b);
  const p95 = lat[Math.floor(lat.length*0.95)];

  const legit = rows.filter(r=>r.kind==='legit'), atk = rows.filter(r=>r.kind==='attack');
  const tp = atk.filter(r=>!r.allow).length, fp = legit.filter(r=>!r.allow).length;
  const byCode = {}; for (const r of atk) if(!r.allow) byCode[r.code]=(byCode[r.code]||0)+1;
  const out = {
    legit:{n:legit.length, passed:legit.length-fp, blocked:fp},
    attack:{n:atk.length, blocked:tp, passed:atk.length-tp},
    TPR:+(tp/atk.length).toFixed(3), FPR:+(fp/legit.length).toFixed(3),
    codes:byCode, G5:g5, legit_p95_ms:p95,
    legit_failures:legit.filter(r=>!r.allow), attack_passes:atk.filter(r=>r.allow), rows
  };
  require('fs').writeFileSync('/tmp/poc33_results2.json', JSON.stringify(out,null,1));
  console.log(JSON.stringify({legit:out.legit, attack:out.attack, TPR:out.TPR, FPR:out.FPR,
    codes:out.codes, G5:out.G5, legit_p95_ms:out.legit_p95_ms,
    attack_passes:out.attack_passes}, null, 1));
})().catch(e=>{console.error('FATAL',e.message);process.exit(1);});
