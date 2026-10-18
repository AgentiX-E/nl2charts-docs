import { AutoTokenizer, AutoModelForSequenceClassification, env } from '@huggingface/transformers';
env.allowLocalModels = false;
env.remoteHost = 'https://hf-mirror.com';
env.remotePathTemplate = '{model}/resolve/{revision}/';

const MODEL = 'Xenova/ms-marco-MiniLM-L-6-v2';
const tok = await AutoTokenizer.from_pretrained(MODEL);
const model = await AutoModelForSequenceClassification.from_pretrained(MODEL, { dtype: 'q8' });

const q = '上月各区域净收入，剔除退款';
const cands = Array.from({length: 40}, (_, i) =>
  i % 4 === 0 ? `列 orders.amount (DECIMAL): 订单金额; 样例 1200.00/980.50 [${i}]`
              : `列 dim_region_${i}.code (VARCHAR): 区域编码; 样例 CN-EAST/CN-SOUTH [${i}]`);

async function rr(docs) {
  const inputs = await tok(docs.map(d => [q, d]), { padding: true, truncation: true });
  const out = await model(inputs);
  return out.logits.tolist();
}
await rr(cands.slice(0,4));

// 串行 40
const serial = [];
for (let i = 0; i < 8; i++) { const t = performance.now(); await rr(cands); serial.push(performance.now()-t); }
serial.sort((a,b)=>a-b);

// 并行分片：4 片 × 10
const shards = [cands.slice(0,10), cands.slice(10,20), cands.slice(20,30), cands.slice(30,40)];
const par4 = [];
for (let i = 0; i < 8; i++) {
  const t = performance.now();
  await Promise.all(shards.map(s => rr(s)));
  par4.push(performance.now()-t);
}
par4.sort((a,b)=>a-b);

// 并行 2 片 × 20
const sh2 = [cands.slice(0,20), cands.slice(20,40)];
const par2 = [];
for (let i = 0; i < 8; i++) {
  const t = performance.now();
  await Promise.all(sh2.map(s => rr(s)));
  par2.push(performance.now()-t);
}
par2.sort((a,b)=>a-b);

// 并发 4 个独立「查询」（模拟多请求）
const q4 = [];
for (let i = 0; i < 6; i++) {
  const t = performance.now();
  await Promise.all([rr(cands.slice(0,10)), rr(cands.slice(0,10)), rr(cands.slice(0,10)), rr(cands.slice(0,10))]);
  q4.push(performance.now()-t);
}
q4.sort((a,b)=>a-b);

console.log('[POC-5c] 并发能力（32 核，单 ORT session）');
console.log(`  串行 40 候选          p50=${serial[4].toFixed(1)}ms`);
console.log(`  2 片并行 (2×20)       p50=${par2[4].toFixed(1)}ms`);
console.log(`  4 片并行 (4×10)       p50=${par4[4].toFixed(1)}ms`);
console.log(`  4 并发独立调用(各10)   p50=${q4[3].toFixed(1)}ms`);
console.log(`\n  → 并行收益: 串行/4片 = ${(serial[4]/par4[4]).toFixed(2)}×`);
