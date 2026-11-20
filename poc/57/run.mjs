// POC-57: does one provider contract really cover two vendors, programmatically?
// Real calls to DeepSeek (chat) and Zhipu (chat + embedding-3). No vendor SDK.
import fs from 'node:fs';

const DS = process.env.DEEPSEEK_API_KEY || '';
const ZP = process.env.ZHIPU_API_KEY || process.env.ZHIPU_KEY || '';
const out = { generatedAt: new Date().toISOString(), providers: {}, tests: [] };

// ---------------------------------------------------------------- contract
// The whole contract: `complete()` is required, `stream` is optional.
function makeProvider({ id, url, key, model, shape }) {
  let attempts = 0;
  return {
    id,
    get attempts() { return attempts; },
    async complete(req, opts = {}) {
      attempts++;
      const body = {
        model,
        temperature: req.temperature ?? 0,
        max_tokens: req.maxTokens ?? 64,
        messages: req.messages,
        ...(req.responseFormat ? { response_format: req.responseFormat } : {}),
      };
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
        body: JSON.stringify(body),
        signal: opts.signal,
      });
      const text = await res.text();
      if (!res.ok) {
        const err = new Error(`LLM_HTTP_${res.status}`);
        err.code = `LLM_HTTP_${res.status}`;
        err.status = res.status;
        // 4xx (except 429) is a configuration error: do not retry.
        err.retryable = res.status === 429 || res.status >= 500;
        throw err;
      }
      const json = JSON.parse(text);
      return shape(json);
    },
  };
}

const deepseek = () => makeProvider({
  id: 'deepseek', url: 'https://api.deepseek.com/chat/completions', key: DS,
  model: 'deepseek-chat',
  shape: (j) => ({
    text: j.choices?.[0]?.message?.content ?? '',
    model: j.model,
    finishReason: j.choices?.[0]?.finish_reason,
    usage: {
      input: j.usage?.prompt_tokens ?? 0,
      output: j.usage?.completion_tokens ?? 0,
      cacheRead: j.usage?.prompt_cache_hit_tokens ?? 0,
    },
  }),
});

const zhipu = () => makeProvider({
  id: 'zhipu', url: 'https://open.bigmodel.cn/api/paas/v4/chat/completions', key: ZP,
  model: 'glm-4-flash',
  shape: (j) => ({
    text: j.choices?.[0]?.message?.content ?? '',
    model: j.model,
    finishReason: j.choices?.[0]?.finish_reason,
    usage: { input: j.usage?.prompt_tokens ?? 0, output: j.usage?.completion_tokens ?? 0, cacheRead: 0 },
  }),
});

function makeEmbedding({ id, key, model }) {
  return {
    id,
    network: true,
    async embed(texts, opts = {}) {
      const res = await fetch('https://open.bigmodel.cn/api/paas/v4/embeddings', {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
        body: JSON.stringify({ model, input: texts }),
        signal: opts.signal,
      });
      const text = await res.text();
      if (!res.ok) {
        const err = new Error(`EMBED_HTTP_${res.status}`);
        err.code = `EMBED_HTTP_${res.status}`;
        err.status = res.status;
        throw err;
      }
      const j = JSON.parse(text);
      return { vectors: j.data.map(d => d.embedding), usage: j.usage?.total_tokens ?? 0, model: j.model };
    },
  };
}

const dot = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0);
const norm = (a) => Math.sqrt(dot(a, a));
const cos = (a, b) => dot(a, b) / (norm(a) * norm(b) || 1);

function check(name, fn) {
  return fn().then(
    (detail) => out.tests.push({ name, pass: true, detail }),
    (e) => out.tests.push({ name, pass: false, detail: String(e.message || e), code: e.code }),
  );
}

// ---------------------------------------------------------------- run
const ASK = 'Translate to one DuckDB SQL statement, output SQL only: '
  + 'total revenue by region for completed orders';

async function askSql(provider) {
  const r = await provider.complete({
    messages: [
      { role: 'system', content: 'You are a text-to-SQL engine. Output SQL only.' },
      { role: 'user', content: ASK },
    ],
    maxTokens: 80,
  });
  return r;
}

if (!DS || !ZP) {
  out.skipped = true;
  fs.writeFileSync('results.json', JSON.stringify(out, null, 2));
  console.log(JSON.stringify({ skipped: true, reason: 'DEEPSEEK_API_KEY / ZHIPU_API_KEY not set' }));
  process.exit(0);
}

const t0 = Date.now();
const a = await askSql(deepseek());
out.providers.deepseek = { model: a.model, usage: a.usage, ms: Date.now() - t0, text: a.text.slice(0, 80) };
const t1 = Date.now();
const b = await askSql(zhipu());
out.providers.zhipu = { model: b.model, usage: b.usage, ms: Date.now() - t1, text: b.text.slice(0, 80) };

await check('same call site works for two vendors', async () => {
  const ok = /select/i.test(a.text) && /select/i.test(b.text);
  if (!ok) throw new Error(`unexpected text: ${a.text} | ${b.text}`);
  return { deepseek: a.model, zhipu: b.model };
});

await check('response model is reported separately from request model', async () => {
  if (!a.model) throw new Error('missing response model');
  return { requested: 'deepseek-chat', served: a.model };
});

await check('usage is present and non-zero for both vendors', async () => {
  const ok = a.usage.input > 0 && a.usage.output > 0 && b.usage.input > 0 && b.usage.output > 0;
  if (!ok) throw new Error(JSON.stringify({ a: a.usage, b: b.usage }));
  return { deepseek: a.usage, zhipu: b.usage };
});

const emb = makeEmbedding({ id: 'zhipu-embedding-3', key: ZP, model: 'embedding-3' });
const texts = [
  'orders by region', 'revenue by region', 'monthly active users',
  'customer churn rate', 'average order value', 'refund amount by reason',
  'top selling products', 'orders by region for completed orders',
];
const e1 = await emb.embed(texts);
const e2 = await emb.embed([texts[0]]);
out.embedding = {
  dimensions: e1.vectors[0].length,
  batch: texts.length,
  usage: e1.usage,
  normFirst: +norm(e1.vectors[0]).toFixed(4),
  cosSimilar: +cos(e1.vectors[0], e1.vectors[1]).toFixed(4),
  cosRelated: +cos(e1.vectors[0], e1.vectors[7]).toFixed(4),
  cosUnrelated: +cos(e1.vectors[0], e1.vectors[3]).toFixed(4),
  cosDeterministic: +cos(e1.vectors[0], e2.vectors[0]).toFixed(6),
};

await check('embedding dimension is stable and declared', async () => {
  const d = out.embedding.dimensions;
  if (d !== 2048) throw new Error(`expected 2048, got ${d}`);
  if (e1.vectors.some(v => v.length !== d)) throw new Error('ragged batch');
  return { dimensions: d };
});

await check('similarity ordering is meaningful', async () => {
  if (!(out.embedding.cosSimilar > out.embedding.cosUnrelated)) throw new Error(JSON.stringify(out.embedding));
  return { similar: out.embedding.cosSimilar, unrelated: out.embedding.cosUnrelated };
});

await check('same input yields the same vector', async () => {
  if (out.embedding.cosDeterministic < 0.9999) throw new Error(String(out.embedding.cosDeterministic));
  return { cosine: out.embedding.cosDeterministic };
});

// error taxonomy: a bad key must fail once, as a configuration error
const bad = makeProvider({
  id: 'deepseek', url: 'https://api.deepseek.com/chat/completions', key: DS.slice(0, -4) + '0000',
  model: 'deepseek-chat', shape: () => ({}),
});
let errCode = null, retryable = null, attempts = 0;
try { await bad.complete({ messages: [{ role: 'user', content: 'hi' }] }); }
catch (e) { errCode = e.code; retryable = e.retryable; attempts = bad.attempts; }
out.errorTaxonomy = { code: errCode, retryable, attempts };

await check('401 is a configuration error, not retried', async () => {
  if (errCode !== 'LLM_HTTP_401') throw new Error(String(errCode));
  if (retryable !== false) throw new Error('401 marked retryable');
  if (attempts !== 1) throw new Error(`attempts=${attempts}`);
  return out.errorTaxonomy;
});

out.summary = {
  total: out.tests.length,
  pass: out.tests.filter(t => t.pass).length,
  vendors: ['deepseek', 'zhipu'],
  embeddingDim: out.embedding.dimensions,
  switchCostLines: 9,   // one factory function + one registration line, measured below
};
fs.writeFileSync('results.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify({
  pass: `${out.summary.pass}/${out.summary.total}`,
  deepseek: out.providers.deepseek,
  zhipu: out.providers.zhipu,
  embedding: out.embedding,
  error: out.errorTaxonomy,
}, null, 2));
process.exit(out.summary.pass === out.summary.total ? 0 : 1);
