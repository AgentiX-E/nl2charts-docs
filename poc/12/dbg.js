const { DuckDBInstance } = require('@duckdb/node-api');
(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const c = await inst.connect();
  try { await c.run('INSTALL sqlite'); console.log('install ok'); } catch(e){ console.log('install err', e.message); }
  try { await c.run('LOAD sqlite'); console.log('load ok'); } catch(e){ console.log('load err', e.message); }
  try { await c.run(`ATTACH '/tmp/poc12/small.sqlite' AS sq (TYPE sqlite, READ_ONLY)`); console.log('attach ok'); } catch(e){ console.log('attach err', e.message); }
  const r = await c.runAndReadAll('SHOW DATABASES');
  console.log(r.getRows());
  try { console.log((await c.runAndReadAll('SELECT * FROM sq.t')).getRows()); } catch(e){ console.log('query err', e.message); }
})();
