import { readFile } from 'node:fs/promises';
import type { Engine } from '@agentix-e/nl2charts-core';
import { ENGINE_BRAND } from '@agentix-e/nl2charts-core';

export async function createDuckDbNode(cfg: { path: string }): Promise<Engine> {
  await readFile(cfg.path).catch(() => null);
  return { kind: 'duckdb-node', query: async () => [], close: async () => {}, [ENGINE_BRAND]: true } as Engine;
}

export function createAgent(){ return {}; }
