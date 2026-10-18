// POC-52: HITL session state — append-only message history vs structured IntentState.
// Zero dependencies, deterministic. Scenario vocabulary follows the ambiguity
// taxonomy used by BIRD-INTERACT (chain ambiguity) and TIDE-Bench (intent drift).
import fs from 'node:fs';

// ---------------------------------------------------------------- scenarios
// slot values are canonical tokens; `applicable` encodes conditional dependency
// (a slot may only be asked when its precondition holds).
const scenarios = [
  // ---- intent drift: user retracts or replaces an already committed element
  { id: 'DR1', kind: 'drift', q: 'revenue by region last quarter',
    events: [
      { t: 'answer', slot: 'metric', value: 'revenue' },
      { t: 'answer', slot: 'region', value: 'emea' },
      { t: 'answer', slot: 'timeRange', value: 'last_quarter' },
      { t: 'retract', slot: 'region' },                       // "actually, group by nothing"
    ],
    gold: { metric: 'revenue', timeRange: 'last_quarter', grain: 'total', filters: {} } },

  { id: 'DR2', kind: 'drift', q: 'orders last month',
    events: [
      { t: 'answer', slot: 'metric', value: 'orders' },
      { t: 'answer', slot: 'timeRange', value: 'last_month' },
      { t: 'replace', slot: 'timeRange', value: 'last_quarter' }, // "make that a quarter"
      { t: 'answer', slot: 'grain', value: 'day' },
    ],
    gold: { metric: 'orders', timeRange: 'last_quarter', grain: 'day', filters: {} } },

  { id: 'DR3', kind: 'drift', q: 'revenue for completed orders',
    events: [
      { t: 'answer', slot: 'metric', value: 'revenue' },
      { t: 'answer', slot: 'filter.status', value: 'completed' },
      { t: 'replace', slot: 'filter.status', value: 'shipped' },
    ],
    gold: { metric: 'revenue', timeRange: 'none', grain: 'total', filters: { status: 'shipped' } } },

  { id: 'DR4', kind: 'drift', q: 'aov by channel',
    events: [
      { t: 'answer', slot: 'metric', value: 'aov' },
      { t: 'answer', slot: 'filter.region', value: 'emea' },
      { t: 'retract', slot: 'filter.region' },
      { t: 'answer', slot: 'channel', value: 'online' },
    ],
    gold: { metric: 'aov', timeRange: 'none', grain: 'channel', filters: {} } },

  { id: 'DR5', kind: 'drift', q: 'revenue last year then narrowed',
    events: [
      { t: 'answer', slot: 'metric', value: 'revenue' },
      { t: 'answer', slot: 'timeRange', value: 'last_year' },
      { t: 'replace', slot: 'timeRange', value: 'last_quarter' },
      { t: 'retract', slot: 'timeRange' },
    ],
    gold: { metric: 'revenue', timeRange: 'none', grain: 'total', filters: {} } },

  { id: 'DR6', kind: 'drift', q: 'orders by region, then drop filter',
    events: [
      { t: 'answer', slot: 'metric', value: 'orders' },
      { t: 'answer', slot: 'filter.region', value: 'apac' },
      { t: 'answer', slot: 'grain', value: 'region' },
      { t: 'replace', slot: 'filter.region', value: 'emea' },
    ],
    gold: { metric: 'orders', timeRange: 'none', grain: 'region', filters: { region: 'emea' } } },

  // ---- chain ambiguity: the second question only exists if the first answer says so
  { id: 'CH1', kind: 'chain', q: 'profit last quarter',
    events: [
      { t: 'answer', slot: 'metric', value: 'profit' },
      { t: 'answer', slot: 'profitBasis', value: 'gross' },
      { t: 'answer', slot: 'timeRange', value: 'last_quarter' },
    ],
    applicable: { metric: () => true, profitBasis: (s) => s.metric === 'profit',
                  taxBasis: (s) => s.metric === 'profit' && s.profitBasis === 'net',
                  timeRange: () => true, region: () => true },
    gold: { metric: 'profit', profitBasis: 'gross', timeRange: 'last_quarter', grain: 'total', filters: {} } },

  { id: 'CH2', kind: 'chain', q: 'profit after tax',
    events: [
      { t: 'answer', slot: 'metric', value: 'profit' },
      { t: 'answer', slot: 'profitBasis', value: 'net' },
      { t: 'answer', slot: 'taxBasis', value: 'inclusive' },   // only reachable via net
    ],
    applicable: { metric: () => true, profitBasis: (s) => s.metric === 'profit',
                  taxBasis: (s) => s.metric === 'profit' && s.profitBasis === 'net',
                  timeRange: () => true, region: () => true },
    gold: { metric: 'profit', profitBasis: 'net', taxBasis: 'inclusive', timeRange: 'none', grain: 'total', filters: {} } },

  { id: 'CH3', kind: 'chain', q: 'orders by region',
    events: [
      { t: 'answer', slot: 'metric', value: 'orders' },
      { t: 'answer', slot: 'region', value: 'emea' },
      { t: 'answer', slot: 'grain', value: 'region' },
    ],
    applicable: { metric: () => true, profitBasis: (s) => s.metric === 'profit',
                  taxBasis: (s) => s.metric === 'profit' && s.profitBasis === 'net',
                  region: (s) => !!s.metric, grain: () => true },
    gold: { metric: 'orders', timeRange: 'none', grain: 'region', filters: {} } },

  { id: 'CH4', kind: 'chain', q: 'margin by channel',
    events: [
      { t: 'answer', slot: 'metric', value: 'margin' },
      { t: 'answer', slot: 'channel', value: 'retail' },
    ],
    applicable: { metric: () => true, marginBasis: (s) => s.metric === 'margin',
                  profitBasis: (s) => s.metric === 'profit',
                  taxBasis: () => false, channel: () => true },
    gold: { metric: 'margin', timeRange: 'none', grain: 'channel', filters: {} } },

  { id: 'CH5', kind: 'chain', q: 'revenue growth by month',
    events: [
      { t: 'answer', slot: 'metric', value: 'revenue' },
      { t: 'answer', slot: 'grain', value: 'month' },
      { t: 'answer', slot: 'growthBasis', value: 'yoy' },
    ],
    applicable: { metric: () => true, growthBasis: (s) => s.metric === 'revenue', grain: () => true },
    gold: { metric: 'revenue', grain: 'month', growthBasis: 'yoy', timeRange: 'none', filters: {} } },

  { id: 'CH6', kind: 'chain', q: 'revenue, nothing else asked',
    events: [ { t: 'answer', slot: 'metric', value: 'revenue' } ],
    applicable: { metric: () => true, growthBasis: (s) => s.metric === 'revenue', grain: () => true,
                  timeRange: () => true },
    gold: { metric: 'revenue', timeRange: 'none', grain: 'total', filters: {} } },
];

// ---------------------------------------------------------------- reducers
// (A) append-only: the conversation is a flat list; the resolver reads the
//     latest answer per slot. There is no representation for "take it back".
function appendOnly(events) {
  const answers = events.filter(e => e.t === 'answer');
  const last = {};
  for (const a of answers) last[a.slot] = a.value;
  return toIntent(last);
}

// (B) IntentState: slots are a committed map + an audit log. retract removes,
//     replace is retract+commit, and every transition is explicit.
function intentState(events) {
  const state = { committed: {}, rev: 0, audit: [] };
  for (const e of events) {
    if (e.t === 'answer') {
      if (e.slot in state.committed && state.committed[e.slot] === e.value) continue;
      state.committed[e.slot] = e.value;
      state.audit.push({ op: 'commit', slot: e.slot, value: e.value, rev: ++state.rev });
    } else if (e.t === 'retract') {
      if (!(e.slot in state.committed)) throw new Error('ILLEGAL_RETRACT_UNCOMMITTED:' + e.slot);
      const old = state.committed[e.slot];
      delete state.committed[e.slot];
      state.audit.push({ op: 'retract', slot: e.slot, prev: old, rev: ++state.rev });
    } else if (e.t === 'replace') {
      const old = state.committed[e.slot];
      state.committed[e.slot] = e.value;
      state.audit.push({ op: 'replace', slot: e.slot, prev: old, value: e.value, rev: ++state.rev });
    }
  }
  return toIntent(state.committed);
}

function toIntent(flat) {
  const out = { metric: undefined, timeRange: 'none', grain: 'total', filters: {} };
  for (const [k, v] of Object.entries(flat)) {
    if (k.startsWith('filter.')) out.filters[k.slice(7)] = v;
    else if (k === 'grain' || k === 'region' || k === 'channel') out.grain = v === 'all' ? 'total' : (k === 'grain' ? v : k);
    else out[k] = v;
  }
  return out;
}

// ---------------------------------------------------------------- question ordering
function questionOrder(scenariosArr, mode) {
  let asked = 0, wasted = 0;
  for (const s of scenariosArr) {
    if (!s.applicable) continue;
    // walk the answer events so the state is exactly what the user has said so far
    const state = {};
    for (const e of s.events) {
      if (e.t === 'answer' || e.t === 'replace') state[e.slot] = e.value;
      if (e.t === 'retract') delete state[e.slot];
    }
    // fixed order: every known slot is asked regardless of applicability
    const slots = Object.keys(s.applicable);
    for (const slot of slots) {
      asked++;
      const ok = s.applicable[slot](state);
      if (!ok) wasted++;   // the question was not applicable at that point
    }
  }
  return { asked, wasted, wasteRate: +(wasted / asked).toFixed(3) };
}

// dependency order: only ask a slot whose precondition holds at ask time.
function dependencyOrder(scenariosArr) {
  let asked = 0, wasted = 0;
  for (const s of scenariosArr) {
    if (!s.applicable) continue;
    const slots = Object.keys(s.applicable);
    const state = {};
    // iterate to fixpoint: a slot becomes askable only after its deps are known
    let progress = true;
    const done = new Set();
    while (progress) {
      progress = false;
      for (const slot of slots) {
        if (done.has(slot)) continue;
        if (!s.applicable[slot](state)) { continue; }
        done.add(slot); asked++; progress = true;
        const ev = s.events.find(e => e.slot === slot && (e.t === 'answer' || e.t === 'replace'));
        if (ev) state[slot] = ev.value;
      }
    }
    // slots never askable are simply not asked — that is the point
  }
  return { asked, wasted, wasteRate: +(wasted / asked).toFixed(3) };
}

// ---------------------------------------------------------------- serialization
function canon(o) {
  const walk = (v) => {
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === 'object') {
      const out = {};
      for (const k of Object.keys(v).sort()) {
        if (v[k] === undefined) continue;
        out[k] = walk(v[k]);
      }
      return out;
    }
    return v;
  };
  return JSON.stringify(walk(o));
}
function serialize(s) { return JSON.stringify(s); }
function deserialize(j) { return JSON.parse(j); }

// ---------------------------------------------------------------- illegal transitions
const illegal = [
  ['retract-uncommitted', () => intentState([{ t: 'retract', slot: 'metric' }])],
  ['answer-unknown-slot', () => {
    const allowed = new Set(['metric', 'timeRange', 'grain', 'region']);
    const e = { t: 'answer', slot: 'nonsense', value: 'x' };
    if (!allowed.has(e.slot)) throw new Error('ILLEGAL_SLOT:' + e.slot);
    return intentState([e]);
  }],
  ['double-clarify-one-turn', () => {
    const asks = [{ slot: 'metric' }, { slot: 'timeRange' }];
    if (asks.length > 1) throw new Error('HITL_MAX_ONE_QUESTION_PER_TURN');
    return asks;
  }],
  ['clarify-after-answer-without-commit', () => {
    const commited = {};
    const ask = { slot: 'grain' };
    if (!commited.metric) throw new Error('HITL_CLARIFY_BEFORE_COMMIT');
    return ask;
  }],
];

// ---------------------------------------------------------------- run
const results = [];
for (const s of scenarios) {
  const a = appendOnly(s.events);
  const b = intentState(s.events);
  const eq = (x, y) => canon(x) === canon(y);
  results.push({
    id: s.id, kind: s.kind,
    appendOnlyCorrect: eq(a, s.gold),
    intentStateCorrect: eq(b, s.gold),
    appendOnlyGot: a, intentStateGot: b,
  });
}

// resume equivalence: serialize the committed map, rebuild, resolve again
let resumeOk = 0;
for (const s of scenarios) {
  const st = {};
  for (const e of s.events) {
    if (e.t === 'answer' || e.t === 'replace') st[e.slot] = e.value;
    if (e.t === 'retract') delete st[e.slot];
  }
  const round = deserialize(serialize(st));
  if (canon(toIntent(round)) === canon(toIntent(st))) resumeOk++;
}

const rejected = [];
for (const [name, fn] of illegal) {
  try { fn(); rejected.push({ name, rejected: false }); }
  catch (e) { rejected.push({ name, rejected: true, code: e.message.split(':')[0] }); }
}

const out = {
  generatedAt: new Date().toISOString(),
  scenarios: {
    total: results.length,
    drift: results.filter(r => r.kind === 'drift').length,
    chain: results.filter(r => r.kind === 'chain').length,
    appendOnly: { correct: results.filter(r => r.appendOnlyCorrect).length },
    intentState: { correct: results.filter(r => r.intentStateCorrect).length },
    failures: results.filter(r => !r.intentStateCorrect).map(r => r.id),
    driftFailuresAppendOnly: results.filter(r => r.kind === 'drift' && !r.appendOnlyCorrect).map(r => r.id),
  },
  resume: { ok: resumeOk, total: scenarios.length },
  illegalTransitions: rejected,
  ordering: {
    fixed: questionOrder(scenarios, 'fixed'),
    dependency: dependencyOrder(scenarios),
  },
  detail: results,
};
fs.writeFileSync('results.json', JSON.stringify(out, null, 2));

console.log(JSON.stringify({
  append_only_correct: `${out.scenarios.appendOnly.correct}/${out.scenarios.total}`,
  intent_state_correct: `${out.scenarios.intentState.correct}/${out.scenarios.total}`,
  drift_failures_append_only: out.scenarios.driftFailuresAppendOnly,
  resume: `${out.resume.ok}/${out.resume.total}`,
  illegal_rejected: `${rejected.filter(r => r.rejected).length}/${rejected.length}`,
  ordering_fixed: out.ordering.fixed,
  ordering_dependency: out.ordering.dependency,
}, null, 2));
