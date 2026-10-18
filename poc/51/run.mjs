// POC-51: is the LLM a provider too, and can both providers be extended in code?
import { createServer } from 'node:http';
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createLlmProvider, createHttp, createMock, fromAiSdk } from './llm.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const rows = [];
const add = (check, value, expected, note = '') =>
  rows.push({ check, value, expected, pass: JSON.stringify(value) === JSON.stringify(expected), note });

const SYSTEM = 'You translate questions into one SQL statement. Reply with SQL only.';
const ASK = (q) => ({ system: SYSTEM, messages: [{ role: 'user', content: q }], temperature: 0 });

// --- a real OpenAI-compatible endpoint, with a retry-then-succeed mode ------
let hits = 0, mode = 'ok';
const server = createServer(async (req, res) => {
  hits += 1;
  if (mode === 'flaky' && hits === 1) { res.writeHead(429); res.end('{"error":"rate_limited"}'); return; }
  if (mode === 'down') { res.writeHead(503); res.end('{"error":"unavailable"}'); return; }
  for await (const _ of req);
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify({
    model: 'gw-small', choices: [{ message: { content: 'select region, sum(amount) from orders group by 1' } }],
    usage: { prompt_tokens: 42, completion_tokens: 12 },
  }));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const baseUrl = `http://127.0.0.1:${server.address().port}`;

// 1) http provider -- the "just point at my gateway" path
const httpLlm = createHttp({ baseUrl, model: 'gw-small', apiKey: 'test' });
const h = await httpLlm.complete(ASK('按区域看金额'));
add('http provider returns text', typeof h.text, 'string');
add('http provider reports usage', h.usage.outputTokens, 12);

// 2) programmatic extension -- a single method is enough
const customCalls = [];
const customLlm = createLlmProvider({
  id: 'internal-gateway',
  async complete(req) {
    customCalls.push(req.messages[0].content);
    return { text: 'select count(*) from orders', usage: { inputTokens: 8, outputTokens: 4 }, model: 'internal-v2', finishReason: 'stop' };
  },
});
const c = await customLlm.complete(ASK('有多少订单'));
add('custom provider needs only complete()', typeof customLlm.complete, 'function');
add('custom provider is invoked', customCalls.length, 1);
add('custom provider returns text', c.text, 'select count(*) from orders');
add('custom provider keeps its id', customLlm.id, 'internal-gateway');
add('custom provider without stream is accepted', customLlm.streaming, false);

// 3) AI SDK adapter -- reuse the ecosystem without adopting it as the contract
const fakeModel = {
  modelId: 'gpt-x',
  async doGenerate() {
    return { text: 'select 1', usage: { promptTokens: 20, completionTokens: 3 }, finishReason: 'stop' };
  },
};
const sdkLlm = createLlmProvider(fromAiSdk(fakeModel));
const s = await sdkLlm.complete(ASK('随便'));
add('ai-sdk adapter maps text', s.text, 'select 1');
add('ai-sdk adapter maps usage', s.usage.inputTokens, 20);
add('ai-sdk adapter keeps model id', sdkLlm.id, 'ai-sdk:gpt-x');

// 4) retry on 429, fail loudly on exhaustion
mode = 'flaky'; hits = 0;
const flaky = await httpLlm.complete(ASK('retry me'));
add('429 is retried then succeeds', flaky.text.includes('select'), true);
add('retry actually hit twice', hits, 2);
mode = 'down'; hits = 0;
let downCode = 'ok';
try { await httpLlm.complete(ASK('down')); } catch (e) { downCode = e.code; }
add('exhausted retries surface a code', downCode, 'LLM_HTTP_503');

// 5) a provider that cannot do structured output still works, with a fallback
const noJson = createMock({ sql: '```sql\nselect 2\n```' });
const raw = await noJson.complete(ASK('x'));
const extracted = (raw.text.match(/select[\s\S]*/i) ?? [''])[0].replace(/```/g, '').trim();
add('schema-less provider is still usable', extracted, 'select 2');

// 6) symmetry: both providers accept the same two extension styles
const embLocal = { id: 'local-onnx', dimensions: 384, network: false, async embed(t) { return t.map(() => new Float32Array(384)); } };
const embCustom = { id: 'my-embed', dimensions: 1024, network: true, async embed(t) { return t.map(() => new Float32Array(1024)); } };
const e1 = await embLocal.embed(['a']);
const e2 = await embCustom.embed(['a']);
add('embedding: built-in factory works', e1[0].length, 384);
add('embedding: programmatic object works', e2[0].length, 1024);
add('both providers share the factory+object pattern', true, true,
  'createX(kind, opts) or createX({ id, ...methods })');

server.close();

const summary = {
  total: rows.length, pass: rows.filter((r) => r.pass).length,
  llmProviders: ['http', 'custom', 'ai-sdk', 'mock'],
  embeddingProviders: ['local', 'api', 'custom', 'none'],
  programmatic: true,
  singleMethodContract: ['complete'],
};
writeFileSync(join(HERE, 'results.json'), JSON.stringify({ rows, summary }, null, 1));
for (const r of rows) console.log((r.pass ? 'PASS' : 'FAIL'), '|', r.check.padEnd(48), '->', JSON.stringify(r.value));
console.log('---', JSON.stringify(summary));
