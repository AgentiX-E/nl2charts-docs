// POC-53: is "align with OTel GenAI semconv" a contract we can rely on?
// Three measurements:
//   1. attribute-name survival across semconv versions (documented rename history)
//   2. four canonical dashboards under three schema vintages -> rows returned
//   3. PII leakage of raw SQL text in span attributes vs hash + external ref
// Plus one real DeepSeek call to check request vs response model and cache tokens.
import fs from 'node:fs';

const KEY = process.env.DEEPSEEK_API_KEY || '';
const out = { generatedAt: new Date().toISOString(), llm: null };

// ------------------------------------------------------------------ 1. schema
// Version -> which of our emitted keys exist under that name.
// Sources: semconv changelog 1.27 / 1.37 / 1.40 / 1.41 / 1.42 / 1.43 (see docs).
const OUR_KEYS = [
  'gen_ai.operation.name', 'gen_ai.provider.name', 'gen_ai.request.model',
  'gen_ai.response.model', 'gen_ai.usage.input_tokens', 'gen_ai.usage.output_tokens',
  'gen_ai.response.finish_reasons', 'gen_ai.tool.name', 'gen_ai.tool.call.id',
  'gen_ai.agent.name', 'gen_ai.agent.id', 'gen_ai.usage.cache_read.input_tokens',
];
const SCHEMAS = {
  'v1.30 (2025-04)': new Set([
    'gen_ai.operation.name', 'gen_ai.request.model', 'gen_ai.response.model',
    'gen_ai.usage.prompt_tokens', 'gen_ai.usage.completion_tokens',
    'gen_ai.response.finish_reasons', 'gen_ai.system', 'gen_ai.prompt', 'gen_ai.completion',
  ]),
  'v1.40 (2026-02)': new Set([
    'gen_ai.operation.name', 'gen_ai.provider.name', 'gen_ai.request.model',
    'gen_ai.response.model', 'gen_ai.usage.input_tokens', 'gen_ai.usage.output_tokens',
    'gen_ai.response.finish_reasons', 'gen_ai.usage.cache_read.input_tokens',
    'gen_ai.input.messages', 'gen_ai.output.messages',
  ]),
  'v1.43+ (2026-07, genai repo)': new Set([
    'gen_ai.operation.name', 'gen_ai.provider.name', 'gen_ai.request.model',
    'gen_ai.response.model', 'gen_ai.usage.input_tokens', 'gen_ai.usage.output_tokens',
    'gen_ai.response.finish_reasons', 'gen_ai.usage.cache_read.input_tokens',
    'gen_ai.agent.name', 'gen_ai.agent.id', 'gen_ai.tool.name', 'gen_ai.tool.call.id',
    'gen_ai.input.messages', 'gen_ai.output.messages',
  ]),
};
const survival = {};
for (const [v, set] of Object.entries(SCHEMAS)) {
  const hit = OUR_KEYS.filter(k => set.has(k));
  survival[v] = { valid: hit.length, total: OUR_KEYS.length, missing: OUR_KEYS.filter(k => !set.has(k)) };
}
out.schemaSurvival = survival;

// ------------------------------------------------------------------ spans
const spans = [];
function span(name, kind, attrs, fn) {
  const s = { name, kind, start: Date.now(), attrs: { ...attrs }, events: [] };
  spans.push(s);
  try { return fn(s); }
  finally { s.end = Date.now(); s.durMs = s.end - s.start; }
}
const PII = {
  phone: /1[3-9]\d{9}/,
  email: /[\w.+-]+@[\w-]+\.[\w.]+/,
  idcard: /\b\d{6}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b/,
};
function piiHits(obj) {
  const text = JSON.stringify(obj);
  return Object.entries(PII).filter(([, re]) => re.test(text)).map(([k]) => k);
}

// a SQL statement a user could plausibly produce, carrying real-format literals
const SQL_WITH_PII =
  "select * from orders where phone = '13800138000' and email = 'alice@example.com' " +
  "and id_no = '110101199001011234'";

function emitTrace({ includeContent, statementMode, withHook }) {
  const trace = [];
  const hook = (e) => { if (withHook) trace.push(e); };
  const local = [];
  const push = (e) => { local.push(e); hook(e); };

  span('invoke_agent ask', 'INTERNAL', {
    'gen_ai.operation.name': 'invoke_agent',
    'gen_ai.agent.name': 'nl2charts',
    'nl2charts.schema': 'nl2charts.span.v1',
  }, () => {
    push({ name: 'invoke_agent ask', attrs: { 'gen_ai.operation.name': 'invoke_agent' } });

    span('chat llm.intent', 'CLIENT', {
      'gen_ai.operation.name': 'chat',
      'gen_ai.provider.name': 'deepseek',
      'gen_ai.request.model': 'deepseek-chat',
      'gen_ai.response.model': 'deepseek-flash',
      'gen_ai.usage.input_tokens': 1204,
      'gen_ai.usage.output_tokens': 86,
      'gen_ai.usage.cache_read.input_tokens': 1024,
      'gen_ai.response.finish_reasons': ['stop'],
    }, (s) => {
      if (includeContent) s.events.push({ name: 'gen_ai.content.prompt', body: 'user: 上季度各区域营收' });
      push({ name: s.name, attrs: s.attrs });
    });

    span('execute_tool guard', 'INTERNAL', {
      'gen_ai.operation.name': 'execute_tool',
      'gen_ai.tool.name': 'guard',
      ...(statementMode === 'raw'
        ? { 'db.statement': SQL_WITH_PII }
        : { 'nl2charts.sql.hash': 'sha256:9f2c…', 'nl2charts.sql.ref': 'trace://abc/sql' }),
    }, (s) => push({ name: s.name, attrs: s.attrs }));

    span('execute_tool engine.query', 'INTERNAL', {
      'gen_ai.operation.name': 'execute_tool', 'gen_ai.tool.name': 'engine.query',
      'nl2charts.engine.version': 'v1.5.6',
    }, (s) => push({ name: s.name, attrs: s.attrs }));
  });

  return { exported: trace, local };
}

const noHook = emitTrace({ includeContent: false, statementMode: 'hash', withHook: false });
const withHook = emitTrace({ includeContent: false, statementMode: 'hash', withHook: true });
out.traceCompleteness = {
  without_onSpan_fields: noHook.local.length,
  with_onSpan_fields: withHook.exported.length,
  identical: JSON.stringify(noHook.local) === JSON.stringify(withHook.exported),
};

const leakRaw = piiHits(emitTrace({ includeContent: true, statementMode: 'raw', withHook: true }).exported);
const leakHash = piiHits(emitTrace({ includeContent: true, statementMode: 'hash', withHook: true }).exported);
out.pii = {
  raw_statement_modes: leakRaw,
  hash_and_ref_modes: leakHash,
  raw_leaks: leakRaw.length,
  hash_leaks: leakHash.length,
};

// ------------------------------------------------------------------ 2. dashboards
// Same data, two vintages. Each vintage's dashboards are written against that
// vintage's own column names; we then run them against the other table.
const T = {
  'v1.30': [{ system: 'deepseek', prompt_tokens: 991, completion_tokens: 120 }],
  'v1.43': [{ provider_name: 'deepseek', input_tokens: 991, output_tokens: 120, cache_read: 768, cache_miss: 223 }],
  'nl2charts.span.v1': [{ provider: 'deepseek', input_tokens: 991, output_tokens: 120, cache_read: 768, cache_miss: 223 }],
};
const Q = {
  'v1.30': { 'provider': r => r.system, 'input tokens': r => r.prompt_tokens, 'cache cost': () => null },
  'v1.43': { 'provider': r => r.provider_name, 'input tokens': r => r.input_tokens, 'cache cost': r => r.cache_read },
  'nl2charts.span.v1': { 'provider': r => r.provider, 'input tokens': r => r.input_tokens, 'cache cost': r => r.cache_read },
};
const run = (qs, table) => Object.fromEntries(Object.entries(qs).map(([n, fn]) => {
  const vals = table.map(fn).filter(v => v !== undefined && v !== null && v !== '');
  return [n, `${vals.length}/${table.length}`];
}));
out.dashboards = {
  oldDashboards_on_ourTable: run(Q['v1.30'], T['v1.43']),
  ourDashboards_on_oldTable: run(Q['v1.43'], T['v1.30']),
  ownSchema_on_ownTable: run(Q['nl2charts.span.v1'], T['nl2charts.span.v1']),
};

// cost: same prompt, provider reports cache hit/miss separately. DeepSeek bills a
// cache-hit token at 1/10 of a miss; ignoring the split overstates cost.
function costModel() {
  const u = out.llm && out.llm.usage && out.llm.usage.second;
  if (!u) return { skipped: true };
  const hit = u.prompt_cache_hit_tokens ?? 0;
  const miss = u.prompt_cache_miss_tokens ?? u.prompt_tokens;
  const naive = u.prompt_tokens;
  const actual = miss + hit * 0.1;
  return {
    prompt_tokens: naive, cache_hit: hit, cache_miss: miss,
    cache_hit_ratio: +(hit / (hit + miss)).toFixed(4),
    naive_units: naive, cache_aware_units: +actual.toFixed(1),
    overcharge_ratio: +(naive / actual).toFixed(2),
    error_pct: +(((naive - actual) / actual) * 100).toFixed(1),
  };
}

// ------------------------------------------------------------------ 3. real LLM call
async function llm() {
  if (!KEY) return { skipped: true };
  const sys = 'You are a text-to-SQL engine. Output only SQL, no prose.';
  const nonce = `session ${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  // long shared prefix so the provider's automatic cache has something to hit
  const schemaText = Array.from({ length: 60 }, (_, i) =>
    `-- table t${i}(id int, region text, amount decimal, status text)`).concat([`-- ${nonce}`]).join('\n');
  const body = {
    model: 'deepseek-chat',
    temperature: 0,
    max_tokens: 120,
    messages: [
      { role: 'system', content: sys + '\n' + schemaText },
      { role: 'user', content: 'total amount by region for orders with status = completed' },
    ],
  };
  const call = async () => {
    const t0 = Date.now();
    const res = await fetch('https://api.deepseek.com/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${KEY}` },
      body: JSON.stringify(body),
    });
    const json = await res.json();
    return { ms: Date.now() - t0, status: res.status, json };
  };
  const first = await call();
  const second = await call();
  const u1 = first.json.usage || {}, u2 = second.json.usage || {};
  return {
    status: [first.status, second.status],
    requestModel: 'deepseek-chat',
    responseModel: first.json.model,
    usage: { first: u1, second: u2 },
    cache: {
      hit1: u1.prompt_cache_hit_tokens ?? null,
      hit2: u2.prompt_cache_hit_tokens ?? null,
      miss1: u1.prompt_cache_miss_tokens ?? null,
      miss2: u2.prompt_cache_miss_tokens ?? null,
    },
    latencyMs: [first.ms, second.ms],
    sql: (first.json.choices?.[0]?.message?.content || '').trim().slice(0, 120),
  };
}

out.llm = await llm();
out.cost = costModel();
fs.writeFileSync('results.json', JSON.stringify(out, null, 2));

const pct = (a, b) => `${a}/${b}`;
console.log(JSON.stringify({
  schema_survival: Object.fromEntries(Object.entries(survival).map(([k, v]) => [k, pct(v.valid, v.total)])),
  trace_completeness: out.traceCompleteness,
  pii_raw_leaks: out.pii.raw_leaks,
  pii_hash_leaks: out.pii.hash_leaks,
  dashboards: out.dashboards,
  cost: costModel(),
  llm: out.llm && !out.llm.skipped ? {
    status: out.llm.status, responseModel: out.llm.responseModel,
    cache: out.llm.cache, usage: out.llm.usage, latencyMs: out.llm.latencyMs,
  } : out.llm,
}, null, 2));
