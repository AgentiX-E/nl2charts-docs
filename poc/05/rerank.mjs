import { AutoTokenizer, AutoModelForSequenceClassification, env } from '@huggingface/transformers';
env.allowLocalModels = false;
env.remoteHost = 'https://hf-mirror.com';
env.remotePathTemplate = '{model}/resolve/{revision}/';

const MODEL = process.env.M || 'Xenova/bge-reranker-base';
console.log('loading', MODEL);
const t0 = performance.now();
const tok = await AutoTokenizer.from_pretrained(MODEL);
const model = await AutoModelForSequenceClassification.from_pretrained(MODEL, { dtype: 'q8' });
console.log(`load ${((performance.now()-t0)/1000).toFixed(1)}s`);

// 模拟 schema linking 重排：1 query × 40 candidates
const query = '上月各区域净收入，剔除退款';
const cands = Array.from({length: 40}, (_, i) => i % 4 === 0
  ? `列 orders.amount（DECIMAL）：订单金额；样例值 1200.00 / 980.50 / 340.00 [${i}]`
  : `列 dim_region_${i}.code（VARCHAR）：区域编码；样例值 CN-EAST / CN-SOUTH [${i}]`);

async function rerank(q, docs) {
  const pairs = docs.map(d => [q, d]);
  const inputs = await tok(pairs, { padding: true, truncation: true, max_length: 512 });
  const out = await model(inputs);
  const logits = out.logits.tolist();
  return logits.map(r => r.length > 1 ? r[1] : r[0]);
}

// warmup
await rerank(query, cands.slice(0, 8));

const N = 12, times = [];
for (let i = 0; i < N; i++) {
  const t = performance.now();
  await rerank(query, cands);
  times.push(performance.now() - t);
}
times.sort((a,b)=>a-b);
const p = q => times[Math.min(times.length-1, Math.floor(q*times.length))].toFixed(1);
console.log(`[POC-5] rerank 40 pairs: n=${N} p50=${p(.5)}ms p95=${p(.95)}ms max=${times.at(-1).toFixed(1)}ms`);

// 批量大小敏感性
for (const k of [10, 20, 40]) {
  const ts = [];
  for (let i = 0; i < 6; i++) {
    const t = performance.now(); await rerank(query, cands.slice(0, k)); ts.push(performance.now()-t);
  }
  ts.sort((a,b)=>a-b);
  console.log(`   topK=${k}: p50=${ts[3].toFixed(1)}ms`);
}
