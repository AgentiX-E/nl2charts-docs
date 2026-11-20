import { Worker } from 'node:worker_threads';
const q = '上月各区域净收入，剔除退款';
const mk = i => i % 4 === 0 ? `列 orders.amount (DECIMAL): 订单金额; 样例 1200.00/980.50 [${i}]`
                            : `列 dim_region_${i}.code (VARCHAR): 区域编码; 样例 CN-EAST/CN-SOUTH [${i}]`;
const cands = Array.from({length: 40}, (_, i) => mk(i));

const N = 4;
const ws = await Promise.all(Array.from({length: N}, () => new Promise(res => {
  const w = new Worker('./w2.mjs');
  w.once('message', () => res(w));
})));
console.log('workers ready:', N);

const run = (w, docs) => new Promise(res => {
  const h = m => { w.off('message', h); res(m); };
  w.once('message', h); w.postMessage(docs);
});

// warmup
await Promise.all(ws.map(w => run(w, cands.slice(0,3))));

// 4 worker × 10 候选并行
const shards = [cands.slice(0,10), cands.slice(10,20), cands.slice(20,30), cands.slice(30,40)];
const t4 = [];
for (let i = 0; i < 6; i++) {
  const t = performance.now();
  await Promise.all(ws.map((w, j) => run(w, shards[j])));
  t4.push(performance.now()-t);
}
t4.sort((a,b)=>a-b);

// 单 worker 40 候选（对照）
const t1 = [];
for (let i = 0; i < 6; i++) {
  const t = performance.now();
  await run(ws[0], cands);
  t1.push(performance.now()-t);
}
t1.sort((a,b)=>a-b);

console.log(`[POC-5d] 单 worker 串行 40 候选   p50=${t1[3].toFixed(1)}ms`);
console.log(`[POC-5d] 4 worker 并行 4×10        p50=${t4[3].toFixed(1)}ms`);
console.log(`  → 多进程并行收益: ${(t1[3]/t4[3]).toFixed(2)}×`);
for (const w of ws) await w.terminate();
