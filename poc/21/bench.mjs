const t0 = performance.now();
const { renderSVG } = await import('./chart-lib.js');
const tImport = performance.now() - t0;
const spec = { mark: 'bar', categories: ['一月','二月','三月','四月','五月','六月'],
  series: [{ name: '营收', data: [120,200,150,80,170,230] }, { name: '成本', data: [60,90,70,40,80,110] }] };
const t1 = performance.now(); renderSVG(spec, 640, 360); const first = performance.now() - t1;
for (let i=0;i<20;i++) renderSVG(spec);
const times=[];
for (let i=0;i<300;i++){ const a=process.hrtime.bigint(); const s=renderSVG(spec,640,360); times.push(Number(process.hrtime.bigint()-a)/1e6); }
times.sort((a,b)=>a-b);
const q=p=>times[Math.floor(p*(times.length-1))].toFixed(2);
console.log(JSON.stringify({ importMs:+tImport.toFixed(1), firstRenderMs:+first.toFixed(1), p50:+q(0.5), p95:+q(0.95), p99:+q(0.99) }));
