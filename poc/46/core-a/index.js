export const ENGINE_BRAND = Symbol.for('nl2charts.engine');
export class EngineBase {
  constructor(kind) { this.kind = kind; this[ENGINE_BRAND] = true; }
  async query() { return []; }
  async close() {}
}
export const isEngine = (v) => typeof v === 'object' && v !== null && v[ENGINE_BRAND] === true;
export function createAgent(cfg) {
  // guard: only accept what this copy recognises
  if (cfg.engine && !isEngine(cfg.engine)) throw new Error('NOT_AN_ENGINE');
  return { ask: async (q) => ({ sql: `select 1 /* ${q} */` }) };
}
