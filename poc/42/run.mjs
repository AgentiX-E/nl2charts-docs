import { createServer } from 'node:http';
import { Hono } from 'hono';
import { createAdminHandler } from './handler.mjs';

const store = { version: '3.0', models: ['sales'] };
const handle = createAdminHandler(store);

// 1) direct
const direct = async (method, path, body) =>
  handle(new Request(`http://x/admin/v1${path}`, { method, body: body ? JSON.stringify(body) : undefined }));

// 2) hono
const app = new Hono();
app.all('/admin/v1/*', (c) => handle(c.req.raw));
const viaHono = (method, path, body) =>
  app.fetch(new Request(`http://x/admin/v1${path}`, { method, body: body ? JSON.stringify(body) : undefined }));

// 3) node:http
const server = createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const init = { method: req.method, headers: req.headers };
  if (chunks.length) init.body = Buffer.concat(chunks);
  const resp = await handle(new Request(`http://${req.headers.host}${req.url}`, init));
  res.writeHead(resp.status, { 'content-type': resp.headers.get('content-type') ?? 'text/plain' });
  res.end(Buffer.from(await resp.arrayBuffer()));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
const viaHttp = async (method, path, body) => {
  const r = await fetch(`http://127.0.0.1:${port}/admin/v1${path}`, {
    method, headers: { 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => null) };
};

const cases = [['GET', '/health'], ['GET', '/models'], ['POST', '/models', { name: 'ops' }], ['POST', '/models', {}]];
const rows = [];
for (const [m, p, b] of cases) {
  const d = await direct(m, p, b);
  const h = await viaHono(m, p, b);
  const n = await viaHttp(m, p, b);
  const dj = await d.json().catch(() => null);
  const hj = await h.json().catch(() => null);
  rows.push({ case: `${m} ${p}${b ? ' ' + JSON.stringify(b) : ''}`, direct: d.status, hono: h.status, http: n.status,
    sameBody: JSON.stringify(dj) === JSON.stringify(hj) && JSON.stringify(dj) === JSON.stringify(n.json) });
}
console.log(JSON.stringify(rows, null, 1));
import('node:fs').then(fs=>fs.writeFileSync('admin.json', JSON.stringify(rows, null, 1)));
server.close();
