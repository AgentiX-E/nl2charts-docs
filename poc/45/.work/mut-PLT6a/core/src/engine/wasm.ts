import type { Engine } from './contract';
import { ENGINE_BRAND } from './contract';
export async function createDuckDbWasm(): Promise<Engine> {
  return { kind: 'duckdb-wasm', query: async () => [], close: async () => {}, [ENGINE_BRAND]: true } as Engine;
}
