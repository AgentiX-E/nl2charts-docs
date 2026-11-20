import { Worker } from 'node:worker_threads';
const q = '上月各区域净收入，剔除退款';
const mk = i => i % 4 === 0 ? `列 orders.amount (DECIMAL): 订单金额; 样例 1200.00/980.50 [${i}]`
                            : `列 dim_region_${i}.code (VARCHAR): 区域编码; 样例 CN-EAST/CN-SOUTH [${i}]`;
const cands = Array.from({length: 40}, (_, i) => mk(i));

const mkPool = async (N) => Promise.all(Array.from({length: N}, () => new Promise(res => {
  const w = new Worker('./w2.mjs'); w.once('message', () => res(w));
})));
const run = (w, docs) => new Promise(res => { const h = m => { w.off('message', h); res(m); }; w.once('message', h); w.postMessage(docs); });
const pct = (ts, x) => ts[Math.min(ts.length-1, Math.floor(x*ts.length))].toFixed(1);

for (const N of [2, 4, 8]) {
  const pool = await mkPool(N);
  await Promise.all(pool.map(w => run(w, cands.slice(0,2))));
  const shard = (arr, n) => { const out=[]; const sz=Math.ceil(arr.length/n); for(let i=0;i<n;i++) out.push(arr.slice(i*sz,(i+1)*sz)); return out.filter(s=>s.length); };
  const ts = [];
  for (let i = 0; i < 20; i++) {
    const sh = shard(cands, N);
    const t = performance.now();
    await Promise.all(pool.map((w, j) => run(w, sh[j] ?? [])));
    ts.push(performance.now()-t);
  }
  ts.sort((a,b)=>a-b);
  console.log(`  ${N} worker × 40 候选: p50=${pct(ts,.5).padStart(6)}ms p95=${pct(ts,.95).padStart(6)}ms max=${ts.at(-1).toFixed(1)}ms`);
  for (const w of pool) await w.terminate();
}

// 20 候选 / 12 候选
const pool = await mkPool(4);
await Promise.all(pool.map(w => run(w, cands.slice(0,2))));
const shard = (arr,n)=>{const out=[];const sz=Math.ceil(arr.length/n);for(let i=0;i<n;i++)out.push(arr.slice(i*sz,(i+1)*sz));return out.filter(s=>s.length);};
for (const K of [20, 12]) {
  const ts = [];
  for (let i = 0; i < 20; i++) {
    const sh = shard(cands.slice(0,K), 4);
    const t = performance.now();
    await Promise.all(pool.map((w,j)=>run(w, sh[j] ?? [])));
    ts.push(performance.now()-t);
  }
  ts.sort((a,b)=>a-b);
  console.log(`  4 worker × ${K} 候选: p50=${pct(ts,.5).padStart(6)}ms p95=${pct(ts,.95).padStart(6)}ms`);
}
for (const w of pool) await w.terminate();
