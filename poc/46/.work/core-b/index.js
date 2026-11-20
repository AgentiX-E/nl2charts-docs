export const ENGINE_BRAND = Symbol.for('nl2charts.engine');
export class EngineBase {
  constructor(kind) { this.kind = kind; this[ENGINE_BRAND] = true; }
  async query() { return []; }
  async close() {}
}
export const isEngine = (v) => typeof v === 'object' && v !== null && (v[ENGINE_BRAND]) === true;
export function createAgent(cfg) {
  if (cfg.engine && !isEngine(cfg.engine)) throw new Error('NOT_AN_ENGINE');
  return { ask: async (q) => ({ sql: 'select 1' }) };
}
// naive registry: one Map per physical copy
export const NAIVE = new Map();
export function naiveRegister(k, v) { NAIVE.set(k, v); }
export function naiveResolve(k) { return NAIVE.get(k) ?? null; }
// shared registry: process-wide, keyed by a registered symbol
const KEY = Symbol.for('nl2charts.registry');
export const SHARED = (globalThis[KEY] ??= new Map());
export function register(k, v) { SHARED.set(k, v); }
export function resolve(k) { return SHARED.get(k) ?? null; }
