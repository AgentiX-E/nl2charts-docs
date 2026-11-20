import { AutoTokenizer, AutoModelForSequenceClassification, env } from '@huggingface/transformers';
env.allowLocalModels = false;
env.remoteHost = 'https://hf-mirror.com';
env.remotePathTemplate = '{model}/resolve/{revision}/';
import os from 'node:os';
console.log('cpus:', os.cpus().length);

const q = '上月各区域净收入，剔除退款';
const cands = Array.from({length: 40}, (_, i) =>
  i % 4 === 0 ? `列 orders.amount (DECIMAL): 订单金额; 样例 1200.00/980.50 [${i}]`
              : `列 dim_region_${i}.code (VARCHAR): 区域编码; 样例 CN-EAST/CN-SOUTH [${i}]`);

for (const [dtype, label] of [['q8','q8(量化)'], ['fp32','fp32']]) {
  const MODEL = 'Xenova/ms-marco-MiniLM-L-6-v2';
  const tok = await AutoTokenizer.from_pretrained(MODEL);
  const model = await AutoModelForSequenceClassification.from_pretrained(MODEL, { dtype });
  async function rr(docs) {
    const inputs = await tok(docs.map(d => [q, d]), { padding: true, truncation: true });
    const out = await model(inputs);
    return out.logits.tolist();
  }
  await rr(cands.slice(0,4));
  for (const k of [8, 20, 40]) {
    const ts = [];
    for (let i = 0; i < 8; i++) { const t = performance.now(); await rr(cands.slice(0,k)); ts.push(performance.now()-t); }
    ts.sort((a,b)=>a-b);
    console.log(`  ${label} topK=${String(k).padStart(2)} p50=${ts[4].toFixed(1).padStart(6)}ms`);
  }
  await model.dispose?.();
}
