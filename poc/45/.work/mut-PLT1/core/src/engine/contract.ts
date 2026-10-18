export interface Engine {
  readonly kind: string;
  query(sql: string): Promise<Record<string, unknown>[]>;
  close(): Promise<void>;
}
export const ENGINE_BRAND = Symbol.for('nl2charts.engine');
export const isEngine = (v: unknown): v is Engine =>
  typeof v === 'object' && v !== null && (v as Record<symbol, unknown>)[ENGINE_BRAND] === true;
