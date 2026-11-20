import { AutoTokenizer, AutoModelForSequenceClassification, env } from '@huggingface/transformers';
env.allowLocalModels = false;
env.remoteHost = 'https://hf-mirror.com';
env.remotePathTemplate = '{model}/resolve/{revision}/';

const MODEL = 'Xenova/ms-marco-MiniLM-L-6-v2';
const tok = await AutoTokenizer.from_pretrained(MODEL);
const model = await AutoModelForSequenceClassification.from_pretrained(MODEL, { dtype: 'q8' });

const q = '上月各区域净收入，剔除退款';
// 真实长度候选（schema card 里的列描述，约 25-40 token）
const mk = (i) => i % 4 === 0
  ? `列 orders.amount (DECIMAL): 订单金额; 样例 1200.00/980.50 [${i}]`
  : `列 dim_region_${i}.code (VARCHAR): 区域编码; 样例 CN-EAST/CN-SOUTH [${i}]`;
const cands = Array.from({length: 60}, (_, i) => mk(i));

async function rerank(q, docs, opts = {}) {
  const inputs = await tok(docs.map(d => [q, d]), {
    padding: opts.pad ?? true,
    truncation: true,
    ...(opts.maxLen ? { max_length: opts.maxLen } : {}),
  });
  const out = await model(inputs);
  return out.logits.tolist().map(r => r.length > 1 ? r[1] : r[0]);
}

const bench = async (label, docs, opts, n = 10) => {
  await rerank(q, docs.slice(0, 4), opts);
  const ts = [];
  for (let i = 0; i < n; i++) { const t = performance.now(); await rerank(q, docs, opts); ts.push(performance.now()-t); }
  ts.sort((a,b)=>a-b);
  const p = x => ts[Math.min(ts.length-1, Math.floor(x*ts.length))].toFixed(1);
  console.log(`  ${label.padEnd(38)} p50=${p(.5).padStart(6)}ms p95=${p(.95).padStart(6)}ms`);
  return +p(.5);
};

console.log('[POC-5b] 长度与批量敏感性（MiniLM-L6 q8, Node 单线程 CPU）');
// 消息：max_length=512 会 padding 到 512
const a = await bench('40 pairs, maxLen=512（默认截断上限）', cands.slice(0,40), { maxLen: 512 });
const b = await bench('40 pairs, 动态 padding（无 maxLen）', cands.slice(0,40), {});
const c = await bench('20 pairs, 动态 padding', cands.slice(0,20), {});
const d = await bench('12 pairs, 动态 padding', cands.slice(0,12), {});
const e = await bench('8 pairs, 动态 padding', cands.slice(0,8), {});

// token 数验证
const enc = await tok(cands.slice(0,1).map(x=>[q,x]), { padding: false });
console.log('  单对 token 数:', enc.input_ids.dims);

// 长候选（模拟长 metric 描述）对比
const longCands = cands.slice(0,40).map(x => x + ' ' + '该字段用于财务口径核对，需排除退款与测试订单，且按记账日期归属。'.repeat(6));
const f = await bench('40 pairs, 长文本(~200tok)', longCands, {});
console.log(`\n  短/长 文本比值: ${(f/b).toFixed(2)}×`);
