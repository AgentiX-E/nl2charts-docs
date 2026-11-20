const { DuckDBInstance } = require('@duckdb/node-api');
const J = (x) => JSON.stringify(x, (_, v) => typeof v === 'bigint' ? v.toString() : v);
(async () => {
  const inst = await DuckDBInstance.create(':memory:'); const c = await inst.connect();
  await c.run(`CREATE TABLE orders(order_id BIGINT, region VARCHAR, amount DECIMAL(12,2), status VARCHAR, region_id INT)`);
  await c.run(`INSERT INTO orders VALUES (1,'华东',10.5,'paid',1),(2,'华北',20.5,'paid',2),(3,'华东',5.0,'refunded',1)`);
  const lit = s => "'" + s.replaceAll("'","''") + "'";
  const sql = `SELECT region, status, count(*) c FROM orders GROUP BY GROUPING SETS ((region),(status),())`;
  const ast = JSON.parse((await c.runAndReadAll(`SELECT json_serialize_sql(${lit(sql)})`)).getRows()[0][0]);
  const sql2 = (await c.runAndReadAll(`SELECT json_deserialize_sql(${lit(JSON.stringify(ast))})`)).getRows()[0][0];
  console.log('SQL1:', sql); console.log('SQL2:', sql2);
  console.log('R1:', J((await c.runAndReadAll(sql)).getRows()));
  console.log('R2:', J((await c.runAndReadAll(sql2)).getRows()));
  // AST 差异
  const a2 = JSON.parse((await c.runAndReadAll(`SELECT json_serialize_sql(${lit(sql2)})`)).getRows()[0][0]);
  const strip = (o) => JSON.stringify(o, (k, v) => k === 'location' ? undefined : v);
  console.log('AST equal(ignoring location):', strip(ast) === strip(a2));
  // 打印 GROUP BY 节点
  const found = [];
  (function walk(n, p){ if(!n||typeof n!=='object')return; if(n.class==='GROUP_BY_NODE') found.push({path:p,node:n}); for(const k of Object.keys(n)) walk(n[k], p+'.'+k); })(ast,'');
  console.log('GROUP_BY_NODE1:', J(found[0]?.node)?.slice(0,600));
  const found2 = [];
  (function walk(n, p){ if(!n||typeof n!=='object')return; if(n.class==='GROUP_BY_NODE') found2.push({path:p,node:n}); for(const k of Object.keys(n)) walk(n[k], p+'.'+k); })(a2,'');
  console.log('GROUP_BY_NODE2:', J(found2[0]?.node)?.slice(0,600));
  // CAST 节点的正确结构
  const castAst = JSON.parse((await c.runAndReadAll(`SELECT json_serialize_sql(${lit("SELECT CAST(a AS TIMESTAMP) FROM t")})`)).getRows()[0][0]);
  const cs = [];
  (function walk(n){ if(!n||typeof n!=='object')return; if(n.class==='CAST') cs.push(n); for(const k of Object.keys(n)) walk(n[k]); })(castAst);
  console.log('CAST node:', J(cs[0]));
})().catch(e => console.error('FATAL', e.message));
