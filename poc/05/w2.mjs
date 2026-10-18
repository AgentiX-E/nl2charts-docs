import { parentPort } from 'node:worker_threads';
import { AutoTokenizer, AutoModelForSequenceClassification, env } from '@huggingface/transformers';
env.allowLocalModels = false;
env.remoteHost = 'https://hf-mirror.com';
env.remotePathTemplate = '{model}/resolve/{revision}/';
// 限制每个 session 单线程，避免 N worker × N 线程超订
env.backends.onnx.wasm.numThreads = 1;
const tok = await AutoTokenizer.from_pretrained('Xenova/ms-marco-MiniLM-L-6-v2');
const model = await AutoModelForSequenceClassification.from_pretrained('Xenova/ms-marco-MiniLM-L-6-v2', {
  dtype: 'q8',
  session_options: { intraOpNumThreads: 1, interOpNumThreads: 1 },
});
const q = '上月各区域净收入，剔除退款';
parentPort.on('message', async (docs) => {
  const t = performance.now();
  const inputs = await tok(docs.map(d => [q, d]), { padding: true, truncation: true });
  const out = await model(inputs);
  parentPort.postMessage({ ms: performance.now() - t, n: out.logits.dims[0] });
});
parentPort.postMessage({ ready: true });
