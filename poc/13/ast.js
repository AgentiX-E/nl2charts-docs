const { DuckDBInstance } = require('@duckdb/node-api');
(async () => {
  const inst = await DuckDBInstance.create(':memory:');
  const c = await inst.connect();
  for (const sql of ["SELECT * FROM duckdb_settings()", "SELECT * FROM read_csv('/etc/passwd')", "SELECT * FROM src.orders", "SELECT * FROM src.public.orders"]) {
    const lit = "'" + sql.replaceAll("'", "''") + "'";
    const r = await c.runAndReadAll(`SELECT json_serialize_sql(${lit})`);
    const j = JSON.parse(r.getRows()[0][0]);
    const funcs = [], tables = [];
    (function walk(n, path) {
      if (!n || typeof n !== 'object') return;
      if (n.type === 'BASE_TABLE') tables.push({cat: n.catalog_name, sch: n.schema_name, tab: n.table_name});
      if (n.type && String(n.type).includes('FUNCTION')) funcs.push({type: n.type, name: n.function_name || n.name, schema: n.schema});
      for (const k of Object.keys(n)) walk(n[k], path + '.' + k);
    })(j);
    console.log(sql, '\n  tables=', JSON.stringify(tables), '\n  funcs=', JSON.stringify(funcs));
  }
})();
