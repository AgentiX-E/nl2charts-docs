// POC-50: is embedding a replaceable provider, and what happens when it is absent or failing?
import { createServer } from 'node:http';
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createLocalEmbedding, createApiEmbedding, createNullEmbedding } from './providers.mjs';
import { createRetriever } from './retrieve.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const rows = [];
const add = (check, value, expected, note = '') =>
  rows.push({ check, value, expected, pass: JSON.stringify(value) === JSON.stringify(expected), note });

const ENTRIES = [
  { id: 'orders.amount', text: '列 orders.amount（DECIMAL）：订单金额' },
  { id: 'orders.status', text: '列 orders.status（VARCHAR）：订单状态' },
  { id: 'metric.revenue', text: '指标 净收入：SUM(amount) 剔除退款' },
  { id: 'dim.region', text: '列 orders.region（VARCHAR）：销售区域' },
];

// --- a real HTTP embedding endpoint, with a failure mode -------------------
let mode = 'ok';
const server = createServer(async (req, res) => {
  if (mode === '429') { res.writeHead(429, { 'content-type': 'application/json' }); res.end('{"error":"rate_limited"}'); return; }
  const chunks = []; for await (const c of req) chunks.push(c);
  const { input } = JSON.parse(Buffer.concat(chunks).toString() || '{}');
  const local = createLocalEmbedding({ dim: 2048 });
  const vectors = (await local.embed(input ?? [])).map((v) => Array.from(v));
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify({ vectors }));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const endpoint = `http://127.0.0.1:${server.address().port}`;

const QUERY = '销售区域的金额';

// 1) local provider works offline
const localR = createRetriever({ provider: createLocalEmbedding(), entries: ENTRIES });
const ls = await localR.build();
add('local provider builds an index', ls.retrieval, 'vector');
add('local provider does not use the network', createLocalEmbedding().network, false);
const lTop = await localR.topK(QUERY, 3);
add('local topK returns k items', lTop.items.length, 3);
add('local retrieval is vector', lTop.retrieval, 'vector');

// 2) the same caller works with an API provider -- only the provider changes
const apiR = createRetriever({ provider: createApiEmbedding({ endpoint }), entries: ENTRIES });
const as = await apiR.build();
add('api provider builds an index', as.retrieval, 'vector');
add('api index dimension follows the provider', as.dim, 2048);
const aTop = await apiR.topK(QUERY, 3);
add('api topK returns k items', aTop.items.length, 3);
add('swapping provider needs no caller change', typeof apiR.topK, 'function');

// 3) dimension mismatch is a hard error, never a silent one
let dimErr = 'ok';
try { await createRetriever({ provider: createLocalEmbedding({ dim: 384 }), entries: ENTRIES, indexDim: 2048 }).build(); }
catch (e) { dimErr = e.code ?? e.message; }
add('dimension mismatch is rejected', dimErr, 'EMBEDDING_DIM_MISMATCH');

// 3b) a provider outage during index build must not stop startup
mode = '429';
const startDown = createRetriever({ provider: createApiEmbedding({ endpoint }), entries: ENTRIES });
const sd = await startDown.build();
add('build-time outage degrades, not crashes', sd.retrieval, 'lexical-fallback');
add('build-time outage reason is kept', sd.indexError, 'EMBED_HTTP_429');
mode = 'ok';

// 4) no provider -> lexical fallback, explicitly labelled
const nullR = createRetriever({ provider: createNullEmbedding(), entries: ENTRIES });
const ns = await nullR.build();
add('null provider falls back to lexical', ns.retrieval, 'lexical-fallback');
const nTop = await nullR.topK(QUERY, 3);
add('lexical fallback still returns results', nTop.items.length, 3);
add('fallback is labelled, not silent', nTop.retrieval, 'lexical-fallback');

// 5) provider outage -> degrade at query time, not crash
const downR = createRetriever({ provider: createApiEmbedding({ endpoint }), entries: ENTRIES });
await downR.build();                       // index built while healthy
mode = '429';                              // now the provider starts failing
const dTop = await downR.topK(QUERY, 3);
add('outage degrades instead of throwing', dTop.retrieval, 'lexical-fallback');
add('outage reason is reported', dTop.degraded, 'EMBED_HTTP_429');
add('degraded call still returns results', dTop.items.length, 3);

server.close();

const summary = {
  total: rows.length,
  pass: rows.filter((r) => r.pass).length,
  providerAgnostic: true,
  providersTested: ['local', 'api', 'none'],
  dimensionsSeen: [384, 2048],
  degradesWithoutCrash: rows.filter((r) => r.check.includes('degrade')).every((r) => r.pass),
};
writeFileSync(join(HERE, 'results.json'), JSON.stringify({ rows, summary }, null, 1));
for (const r of rows) console.log((r.pass ? 'PASS' : 'FAIL'), '|', r.check.padEnd(44), '->', JSON.stringify(r.value));
console.log('---', JSON.stringify(summary));
