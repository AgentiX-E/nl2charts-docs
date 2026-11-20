// pure orchestration: no node builtins, no driver imports
export function createAgent(cfg) { return { ask: (q) => ({ q, cfg }) }; }
export const CONTRACT_VERSION = '3.0';
