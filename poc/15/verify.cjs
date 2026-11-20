const fs=require('fs');
const p='/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist';
const {createDuckDB,NODE_RUNTIME,ConsoleLogger}=require(p+'/duckdb-node-blocking.cjs');
const {DuckDBInstance}=require('/tmp/poc1/node_modules/@duckdb/node-api');
(async()=>{
 const inst=await DuckDBInstance.create(':memory:'); const nat=await inst.connect();
 await nat.run(`CREATE TABLE t(id INT, amt DECIMAL(12,2), ts TIMESTAMPTZ, s VARCHAR)`);
 await nat.run(`INSERT INTO t VALUES (1,10.10,TIMESTAMPTZ '2026-10-01 00:00:00+00','中文'),(2,20.20,TIMESTAMPTZ '2026-10-02 00:00:00+00','😀')`);
 await nat.run(`COPY t TO '/tmp/poc15/y.parquet' (FORMAT parquet, COMPRESSION zstd)`);
 await nat.run(`ATTACH '/tmp/poc15/nd.duckdb' AS nd`); await nat.run(`CREATE TABLE nd.t2 AS SELECT 42 x`); await nat.run(`DETACH nd`);
 const db=await createDuckDB({mvp:{mainModule:p+'/duckdb-mvp.wasm'},eh:{mainModule:p+'/duckdb-eh.wasm'}},new ConsoleLogger(),NODE_RUNTIME); await db.instantiate(); const w=db.connect();
 db.registerFileBuffer('y.parquet',new Uint8Array(fs.readFileSync('/tmp/poc15/y.parquet')));
 const t1=w.query(`SELECT count(*) c, sum(amt)::VARCHAR s, min(s) a, max(s) b FROM 'y.parquet'`);
 console.log('PARQUET', t1.toArray().map(r=>[r.c,r.s,r.a,r.b].map(String)));
 db.registerFileBuffer('nd.duckdb',new Uint8Array(fs.readFileSync('/tmp/poc15/nd.duckdb')));
 w.query(`ATTACH 'nd.duckdb' AS nd2`);
 console.log('DUCKDB_FILE', w.query('SELECT * FROM nd2.main.t2').toArray().map(r=>String(r.x)));
})();
