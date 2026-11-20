const { DatabaseSync } = require('node:sqlite');
const fs = require('fs');
const db = new DatabaseSync(':memory:');
db.exec(`
create table orders(id integer, region text, created_at text, amount real, status text);
create table customers(id integer, name text, region text);
insert into orders values (1,'east','2026-01-05',120.5,'paid'),(2,'east','2026-02-11',80.0,'open'),(3,'west','2026-01-20',200.0,'paid'),(4,'west','2026-03-02',50.0,'paid');
insert into customers values (1,'Acme Corp','east'),(2,'Globex','west');
`);
const samples = JSON.parse(fs.readFileSync('samples.json', 'utf8'));
const out = { engine: 'node:sqlite', version: db.prepare('select sqlite_version() v').get().v, results: [] };
for (const s of samples) {
  try { db.prepare(s.sql).all(); out.results.push({ id: s.id, cat: s.cat, ok: true, err: null }); }
  catch (e) { out.results.push({ id: s.id, cat: s.cat, ok: false, err: String(e.message).slice(0, 90) }); }
}
fs.writeFileSync('sqlite.json', JSON.stringify(out, null, 1));
const ok = out.results.filter((r) => r.ok).length;
console.log(`sqlite ${out.version}: ${ok}/${samples.length} executable`);
for (const r of out.results) if (!r.ok) console.log('  FAIL', r.id, r.cat, '|', r.err);
