// naive: module-level map -- one per physical copy
export const NAIVE = new Map();
// correct: process-wide registry behind a registered symbol
const KEY = Symbol.for('nl2charts.registry');
export const SHARED = (globalThis[KEY] ??= new Map());
export function register(kind, factory) { SHARED.set(kind, factory); }
export function resolve(kind) { return SHARED.get(kind) ?? null; }
