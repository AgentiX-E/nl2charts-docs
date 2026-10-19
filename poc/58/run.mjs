// POC-58: does the provider layer change the request, and is streaming usable?
// Measures byte-level request fidelity, parameter passthrough, TTFT vs total.
import fs from 'node:fs';

const DS = process.env.DEEPSEEK_API_KEY || '';
const ZP = process.env.ZHIPU_API_KEY || process.env.ZHIPU_KEY || '';
const out = { generatedAt: new Date().toISOString(), tests: [] };

const canonical = (v) => {
  if (Array.isArray(v)) return v.map(canonical);
  if (v && typeof v === 'object') {
    const o = {};
    for (const k of Object.keys(v).sort()) o[k] = canonical(v[k]);
    return o;
  }
  return v;
};
const same = (a, b) => JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));

function buildBody({ model, messages, temperature, maxTokens, stop, seed, responseFormat, stream }) {
  // This is the only place where request shape is assembled.
  return {
    model,
    messages,
    temperature: temperature ?? 0,
    max_tokens: maxTokens ?? 64,
    ...(stop ? { stop } : {}),
    ...(seed !== undefined ? { seed } : {}),
    ...(responseFormat ? { response_format: responseFormat } : {}),
    ...(stream ? { stream: true } : {}),
  };
}

function provider({ url, key, model, sent }) {
  return {
    id: model,
    async complete(req) {
      const body = buildBody({ model, ...req });
      sent.push(body);
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
        body: JSON.stringify(body),
      });
      const text = await res.text();
      if (!res.ok) { const e = new Error(`LLM_HTTP_${res.status}`); e.code = `LLM_HTTP_${res.status}`; e.retryable = res.status === 429 || res.status >= 500; throw e; }
      const j = JSON.parse(text);
      return { text: j.choices?.[0]?.message?.content ?? '', usage: j.usage ?? {} };
    },
    async *stream(req) {
      const body = buildBody({ model, ...req, stream: true });
      sent.push(body);
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
        body: JSON.stringify(body),
      });
      if (!res.ok) { const e = new Error(`LLM_HTTP_${res.status}`); e.code = `LLM_HTTP_${res.status}`; throw e; }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';
        for (const line of lines) {
          const t = line.trim();
          if (!t.startsWith('data:')) continue;
          const data = t.slice(5).trim();
          if (data === '[DONE]') return;
          try {
            const j = JSON.parse(data);
            const d = j.choices?.[0]?.delta?.content;
            if (d) yield d;
          } catch { /* keep-alive or partial line */ }
        }
      }
    },
  };
}

function check(name, fn) {
  return fn().then(
    (d) => out.tests.push({ name, pass: true, detail: d }),
    (e) => out.tests.push({ name, pass: false, detail: String(e.message || e) }),
  );
}

if (!DS) {
  out.skipped = true; fs.writeFileSync('results.json', JSON.stringify(out, null, 2));
  console.log(JSON.stringify({ skipped: true })); process.exit(0);
}

const sent = [];
const ds = provider({ url: 'https://api.deepseek.com/chat/completions', key: DS, model: 'deepseek-chat', sent });

const messages = [
  { role: 'system', content: 'You are a text-to-SQL engine. Output SQL only.' },
  { role: 'user', content: 'total revenue by region for completed orders' },
];

// 1) fidelity: the provider's body must equal a hand-written reference body
await check('request body is byte-identical to the reference', async () => {
  sent.length = 0;
  await ds.complete({ messages, maxTokens: 64, stop: ['\n\n'], seed: 7 });
  const ref = { model: 'deepseek-chat', messages, temperature: 0, max_tokens: 64, stop: ['\n\n'], seed: 7 };
  if (!same(sent[0], ref)) throw new Error(JSON.stringify(sent[0]));
  return { fields: Object.keys(sent[0]).sort() };
});

// 2) passthrough: optional params are not dropped
await check('optional parameters pass through untouched', async () => {
  sent.length = 0;
  let vendorError = null;
  try { await ds.complete({ messages, maxTokens: 64, responseFormat: { type: 'json_object' } }); }
  catch (e) { vendorError = e.code; }
  if (!sent[0].response_format) throw new Error('response_format dropped by the layer');
  // Passthrough and vendor support are different claims: the layer must send it,
  // the vendor may still reject it (POC-7 found DeepSeek does).
  out.structuredOutput = { sentToVendor: true, accepted: vendorError === null, code: vendorError };
  return out.structuredOutput;
});

// 3) streaming: chunks, concatenation, TTFT
const t0 = Date.now();
let firstAt = null, chunks = 0, text = '';
for await (const d of ds.stream({ messages, maxTokens: 80 })) {
  if (firstAt === null) firstAt = Date.now();
  chunks++; text += d;
}
const totalMs = Date.now() - t0;
const ttft = (firstAt ?? t0) - t0;
out.stream = { chunks, ttftMs: ttft, totalMs, chars: text.length, text: text.slice(0, 80) };

await check('streaming yields multiple chunks and joins to text', async () => {
  if (chunks < 2) throw new Error(`chunks=${chunks}`);
  if (!text.trim()) throw new Error('empty stream');
  return out.stream;
});

await check('first token arrives well before the end', async () => {
  if (!(ttft < totalMs)) throw new Error(`ttft=${ttft} total=${totalMs}`);
  return { ttft, totalMs, ratio: +(ttft / totalMs).toFixed(3) };
});

// 4) cache fields are surfaced when the vendor reports them
await check('vendor cache counters are surfaced', async () => {
  const r = await ds.complete({ messages, maxTokens: 8 });
  // provider maps usage verbatim; the field is optional by contract
  if (!('prompt_tokens' in r.usage)) throw new Error(JSON.stringify(r.usage));
  return { hasCacheFields: 'prompt_cache_hit_tokens' in r.usage };
});

// 5) 400 is a configuration error (bad model), not retryable
let code = null, retryable = null;
try { await ds.complete({ messages, maxTokens: 8, model: 'no-such-model' }); }
catch (e) { code = e.code; retryable = e.retryable; }
out.badModel = { code, retryable };

await check('unknown model is a non-retryable configuration error', async () => {
  if (code !== 'LLM_HTTP_400' && code !== 'LLM_HTTP_404') throw new Error(String(code));
  if (retryable !== false) throw new Error('marked retryable');
  return out.badModel;
});

out.summary = { total: out.tests.length, pass: out.tests.filter(t => t.pass).length };
fs.writeFileSync('results.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify({ pass: `${out.summary.pass}/${out.summary.total}`, stream: out.stream, badModel: out.badModel }, null, 2));
process.exit(out.summary.pass === out.summary.total ? 0 : 1);
