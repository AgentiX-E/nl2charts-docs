// .work/mut-PLT6b/core/src/engine/contract.ts
var ENGINE_BRAND = /* @__PURE__ */ Symbol.for("nl2charts.engine");
var isEngine = (v) => typeof v === "object" && v !== null && v[ENGINE_BRAND] === true;

// .work/mut-PLT6b/core/src/index.ts
var registry = /* @__PURE__ */ new Map();
function register(k, v) {
  registry.set(k, v);
}
function resolve(k) {
  return registry.get(k) ?? null;
}
function createAgent(cfg) {
  return { ask: async (q) => ({ sql: `select 1 /* ${q} */` }) };
}
function negotiate() {
  return "local";
}
export {
  createAgent,
  isEngine,
  negotiate,
  register,
  registry,
  resolve
};
