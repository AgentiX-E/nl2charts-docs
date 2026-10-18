// stub:pg
var pg_default = {};

// mut2/core/src/connectors/pg2.ts
var createPg2 = (cfg) => new pg_default.Client(cfg);

// mut2/core/src/engine/contract.ts
var ENGINE_BRAND = /* @__PURE__ */ Symbol.for("nl2charts.engine");
var isEngine = (v) => typeof v === "object" && v !== null && v[ENGINE_BRAND] === true;

// mut2/core/src/index.ts
function createAgent(cfg) {
  return { ask: async (q) => ({ sql: `select 1 /* ${q} */` }) };
}
function negotiate() {
  return "local";
}
export {
  createAgent,
  createPg2,
  isEngine,
  negotiate
};
