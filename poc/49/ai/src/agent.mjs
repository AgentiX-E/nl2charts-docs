// ai: the only package that may touch a model. It emits SQL and hands it to core.
import { createRunner } from '../../core/src/index.mjs';

export function createAgent(cfg) {
  const runner = createRunner({ engine: cfg.engine });
  return {
    async ask(question) {
      const sql = await cfg.llm.toSql(question, cfg.schema);   // provider-agnostic
      return runner.sql(sql, { path: 'nl' });
    },
  };
}
