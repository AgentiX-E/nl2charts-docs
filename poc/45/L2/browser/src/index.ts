import type { Engine } from '@agentix-e/nl2charts-core';
import { ENGINE_BRAND } from '@agentix-e/nl2charts-core';

export async function createDuckDbWasm(cfg: { opfs?: boolean }): Promise<Engine> {
  return { kind: 'duckdb-wasm', query: async () => [], close: async () => {}, [ENGINE_BRAND]: true } as Engine;
}
