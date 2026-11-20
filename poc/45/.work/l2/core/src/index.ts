export interface Engine {
  readonly kind: string;
  query(sql: string): Promise<Record<string, unknown>[]>;
  close(): Promise<void>;
}
export const ENGINE_BRAND = Symbol.for('nl2charts.engine');
export const isEngine = (v: unknown): v is Engine =>
  typeof v === 'object' && v !== null && (v as Record<symbol, unknown>)[ENGINE_BRAND] === true;
export interface AgentConfig { readonly engine?: unknown; readonly llm?: unknown }
export interface Agent { readonly ask: (q: string) => Promise<{ sql: string }> }
export function createAgent(cfg: AgentConfig): Agent {
  return { ask: async (q: string) => ({ sql: `select 1 /* ${q} */` }) };
}
export function negotiate(): 'local' | 'remote' { return 'local'; }
