import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
export async function createDuckDbNode(cfg) {
  const require = createRequire(import.meta.url);
  return { kind: 'duckdb-node', cfg, load: () => readFile(cfg.path) };
}
