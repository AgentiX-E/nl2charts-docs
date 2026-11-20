import { statSync } from 'node:fs';
export const createDuckDbNode = () => ({ kind: 'duckdb-node', p: statSync });