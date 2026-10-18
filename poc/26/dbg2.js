const { DuckDBInstance } = require('@duckdb/node-api');
const lit = s => "'" + s.replaceAll("'","''") + "'";
(async () => {
  const inst = await DuckDBInstance.create(':memory:'); const c = await inst.connect();
  const q = async (sql) => { try { return { ok:true, rows:(await c.runAndReadAll(sql)).getRows() }; } catch(e){ return { ok:false, err:String(e.message).slice(0,120) }; } };
  const ast = (await q(`SELECT json_serialize_sql(${lit("SELECT CAST(a AS TIMESTAMP) AS x FROM t")})`)).rows[0][0];
  console.log('RAW_AST:', ast.slice(0, 700));
  // 只改 query_location 的值，不改结构
  const t1 = JSON.parse(ast); t1.query_location = 999;
  console.log('SET_ROOT_LOC:', JSON.stringify(await q(`SELECT json_deserialize_sql(${lit(JSON.stringify(t1))})`)));
  // 去掉 query_location
  const t2 = JSON.parse(ast); delete t2.query_location;
  console.log('DEL_ROOT_LOC:', JSON.stringify(await q(`SELECT json_deserialize_sql(${lit(JSON.stringify(t2))})`)));
  // 只动第一个 select 节点里的 CAST
  const t3 = JSON.parse(ast);
  const find = (n, cb) => { if(!n||typeof n!=='object')return; cb(n); for(const k of Object.keys(n)) find(n[k], cb); };
  find(t3, n => { if (n.class==='CAST') n.query_location = 12345; });
  console.log('SET_CAST_LOC:', JSON.stringify(await q(`SELECT json_deserialize_sql(${lit(JSON.stringify(t3))})`)));
})().catch(e=>console.error('FATAL',e.message));
