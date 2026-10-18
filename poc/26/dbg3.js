const { DuckDBInstance } = require('@duckdb/node-api');
const lit = s => "'" + s.replaceAll("'","''") + "'";
(async () => {
  const inst = await DuckDBInstance.create(':memory:'); const c = await inst.connect();
  const q = async (sql) => { try { return { ok:true, rows:(await c.runAndReadAll(sql)).getRows() }; } catch(e){ return { ok:false, err:String(e.message).slice(0,120) }; } };
  const ser = async (sql) => JSON.parse((await q(`SELECT json_serialize_sql(${lit(sql)})`)).rows[0][0].replace(/^\{"error":false,"statements":\[/,'{'));
  const getTree = async (sql) => { const r = await q(`SELECT json_serialize_sql(${lit(sql)})`); const j = JSON.parse(r.rows[0][0]); return j; };
  const de = async (tree) => await q(`SELECT json_deserialize_sql(${lit(JSON.stringify(tree))})`);
  const findClass = (n, cls, out=[]) => { if(!n||typeof n!=='object')return out; if(n.class===cls) out.push(n); for(const k of Object.keys(n)) findClass(n[k], cls, out); return out; };

  // A) 只改函数名（不构造新节点）
  const src = `SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+00', '%Y-%m') AS m`;
  let j = await getTree(src);
  findClass(j, 'FUNCTION').forEach(n => { if (n.function_name === 'strftime') n.function_name = 'strftime'; });
  console.log('A rename-noop:', JSON.stringify(await de(j)).slice(0,160));

  // B) 用"克隆模板"方式构造 CAST（先解析一句含 CAST 的查询，克隆其节点）
  const tmpl = await getTree(`SELECT CAST(a AS TIMESTAMP) FROM t`);
  const tmplCast = findClass(tmpl, 'CAST')[0];
  j = await getTree(src);
  const fn = findClass(j, 'FUNCTION').find(n => n.function_name === 'strftime');
  const cloned = JSON.parse(JSON.stringify(tmplCast));
  cloned.alias = '';
  cloned.child = fn.children[0];
  cloned.cast_type = { id: 'TIMESTAMP', type_info: null };
  cloned.try_cast = false;
  fn.children[0] = cloned;
  const rb = await de(j);
  console.log('B clone-template:', JSON.stringify(rb).slice(0,200));
  if (rb.ok) { const run = await q(rb.rows[0][0]); console.log('   exec:', JSON.stringify(run).slice(0,120)); }
})().catch(e=>console.error('FATAL',e.message));
