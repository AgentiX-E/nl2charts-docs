const http = require('http'), fs = require('fs'), path = require('path'), zlib = require('zlib');
const ROOT = '/tmp/poc32/site';
const MIME = { '.html':'text/html; charset=utf-8', '.js':'text/javascript', '.mjs':'text/javascript',
  '.wasm':'application/wasm', '.parquet':'application/octet-stream' };
const shouldGzip = /\.(js|mjs|html|css|json)$/;
http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  fs.readFile(p, (e, buf) => {
    if (e) { res.writeHead(404); return res.end('nf'); }
    const ext = path.extname(p);
    const headers = { 'Content-Type': MIME[ext] || 'application/octet-stream',
      'Cache-Control': ext === '.parquet' ? 'public, max-age=3600' : 'public, max-age=31536000, immutable' };
    const ae = req.headers['accept-encoding'] || '';
    if (shouldGzip.test(ext) && /gzip/.test(ae)) {
      const gz = zlib.gzipSync(buf, { level: 9 });
      headers['Content-Encoding'] = 'gzip';
      res.writeHead(200, headers); return res.end(gz);
    }
    res.writeHead(200, headers); res.end(buf);
  });
}).listen(8770, () => console.log('8770'));
