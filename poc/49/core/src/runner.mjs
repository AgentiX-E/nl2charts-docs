// core: deterministic path only. No LLM, no embedding, no network beyond the engine.
import { assertReadOnly } from './guard.mjs';

export function createRunner(cfg) {
  if (!cfg?.engine) throw new Error('ENGINE_REQUIRED');
  return {
    /** the SQL-first entry point: caller supplies the SQL, we guard and execute it */
    async sql(text, opts = {}) {
      assertReadOnly(text);
      const rows = await cfg.engine.query(text);
      return {
        sql: text, rows, rowCount: rows.length,
        // provenance must say who authored the SQL: a human ('sql') or a model ('nl')
        provenance: { path: opts.path ?? 'sql', chart: opts.chart === true },
      };
    },
  };
}
