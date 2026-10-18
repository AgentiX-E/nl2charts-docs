import type { DuckDBConnection } from '@duckdb/node-api';
export type { DuckDBConnection };
export type { Engine } from './engine/contract';
export { isEngine } from './engine/contract';

export interface AgentConfig { readonly engine?: unknown; readonly llm?: unknown }
export interface Agent { readonly ask: (q: string) => Promise<{ sql: string }> }

export function createAgent(cfg: AgentConfig): Agent {
  return { ask: async (q: string) => ({ sql: `select 1 /* ${q} */` }) };
}
export function negotiate(): 'local' | 'remote' { return 'local'; }
