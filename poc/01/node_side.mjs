import { DuckDBInstance } from '@duckdb/node-api';
import fs from 'node:fs';

const QUERIES = JSON.parse(fs.readFileSync('/tmp/poc1/queries.json','utf8'));
const inst = await DuckDBInstance.create(':memory:');
const conn = await inst.connect();

const out = {};
for (const {name, sql} of QUERIES) {
  try {
    const reader = await conn.runAndReadAll(sql);
    const cols = reader.columnNames();
    const types = reader.columnTypes().map(t => String(t));
    const rows = reader.getRowObjects();
    out[name] = { cols, types, rows: rows.map(r => cols.map(c => norm(r[c]))) };
  } catch (e) {
    out[name] = { error: String(e.message).split('\n')[0].slice(0,140) };
  }
}
function safeJson(o){ return JSON.stringify(o, (_,x)=> typeof x==='bigint' ? x.toString()+'n' : x); }
function norm(v){
  if (v === null || v === undefined) return null;
  if (typeof v === 'bigint') return {__t:'bigint', v:String(v)};
  if (v instanceof Date) return {__t:'date', v:v.toISOString()};
  if (typeof v === 'object') return {__t:'obj', v:safeJson(v)};
  if (typeof v === 'number') return {__t:'num', v:String(v)};
  return {__t:'str', v:String(v)};
}
fs.writeFileSync('/tmp/poc1/node_out.json', JSON.stringify(out,null,1));
console.log('node ok, queries:', Object.keys(out).length, '| engine:', (await conn.runAndReadAll('select version()')).getRowObjects()[0].v);
console.log(JSON.stringify(out, null, 1).slice(0, 1200));
