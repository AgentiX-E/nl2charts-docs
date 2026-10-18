const { DuckDBInstance } = require('@duckdb/node-api');
const lit = s => "'" + s.replaceAll("'","''") + "'";
(async () => {
  const inst = await DuckDBInstance.create(':memory:'); const c = await inst.connect();
  const ast = (await c.runAndReadAll(`SELECT json_serialize_sql(${lit("SELECT strftime(TIMESTAMPTZ '2026-01-01 00:00:00+00', '%Y-%m') AS m")})`)).getRows()[0][0];
  // 找出所有数字与其中的大整数
  const nums = [...ast.matchAll(/"(\w+)":(\d{16,})/g)].map(m => [m[1], m[2]]);
  console.log('BIG_NUMS:', JSON.stringify(nums));
  // 往返是否丢精度
  const parsed = JSON.parse(ast);
  const restring = JSON.stringify(parsed);
  const reNums = [...restring.matchAll(/"(\w+)":(\d{16,})/g)].map(m => [m[1], m[2]]);
  console.log('AFTER_ROUNDTRIP_BIG_NUMS:', JSON.stringify(reNums));
  console.log('STR_EQ:', restring === ast);
  // 首次差异位置
  let i = 0; while (i < Math.min(ast.length, restring.length) && ast[i] === restring[i]) i++;
  console.log('FIRST_DIFF_AT', i, '\n  orig:', ast.slice(Math.max(0,i-60), i+40), '\n  trip:', restring.slice(Math.max(0,i-60), i+40));
  // 直接传原串 vs 传 restring
  const q = async (s) => { try { return { ok:true, v:(await c.runAndReadAll(s)).getRows()[0][0] }; } catch(e){ return { ok:false, err:e.message.slice(0,100) }; } };
  console.log('DESER_ORIG:', JSON.stringify(await q(`SELECT json_deserialize_sql(${lit(ast)})`)).slice(0,120));
  console.log('DESER_TRIP:', JSON.stringify(await q(`SELECT json_deserialize_sql(${lit(restring)})`)).slice(0,120));
})().catch(e=>console.error('FATAL',e.message));
