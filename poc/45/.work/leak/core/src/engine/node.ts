import { readFile } from 'node:fs/promises';
import type { Engine } from './contract';
import { ENGINE_BRAND } from './contract';
export async function createDuckDbNode(cfg: { path: string }): Promise<Engine> {
  await readFile(cfg.path).catch(() => null);
  return { kind: 'duckdb-node', query: async () => [], close: async () => {}, [ENGINE_BRAND]: true } as Engine;
}
