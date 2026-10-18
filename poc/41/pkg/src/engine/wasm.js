import * as duckdb from '@duckdb/duckdb-wasm';
export async function createDuckDbWasm(cfg) { return { kind: 'duckdb-wasm', bundles: duckdb.selectBundle, cfg }; }
