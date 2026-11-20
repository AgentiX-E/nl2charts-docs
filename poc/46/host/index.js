import { createAgent, isEngine, EngineBase } from '../core-a/index.js';
import { createDuckDbNode } from '../pkg-node/index.js';

const engine = createDuckDbNode();          // built from core-B
const rows = [];

// 1) instanceof across two copies
rows.push({ check: 'engine instanceof EngineBase(A)', value: engine instanceof EngineBase, expected: false });

// 2) Symbol.for brand across two copies
rows.push({ check: 'isEngine(A) sees B engine', value: isEngine(engine), expected: true });

// 3) can copy A accept an engine built by copy B?
let accepted = 'yes';
try { createAgent({ engine }); } catch (e) { accepted = 'rejected: ' + e.message; }
rows.push({ check: 'createAgent(A) accepts B engine', value: accepted, expected: 'yes' });

// 4) identity of the shared symbol
rows.push({ check: 'Symbol.for equal across copies', value: Symbol.for('nl2charts.engine') === (await import('../core-b/index.js')).ENGINE_BRAND, expected: true });

console.log(JSON.stringify(rows, null, 1));
const ok = rows.every((r) => JSON.stringify(r.value) === JSON.stringify(r.expected));
console.log(ok ? 'BRAND SURVIVES' : 'BRAND BROKEN');
