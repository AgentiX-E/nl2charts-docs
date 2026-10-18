// Embedding is a pluggable capability, not a hard-coded vendor.
export function createLocalEmbedding({ dim = 384 } = {}) {
  const bigrams = (s) => { const o = []; for (let i = 0; i < s.length - 1; i++) o.push(s.slice(i, i + 2)); return o; };
  const vec = (s) => {
    const v = new Float32Array(dim);
    for (const g of bigrams(s)) {
      let h = 0;
      for (const c of g) h = (h * 31 + c.codePointAt(0)) >>> 0;
      v[h % dim] += 1;
    }
    let n = 0; for (const x of v) n += x * x; n = Math.sqrt(n) || 1;
    for (let i = 0; i < dim; i++) v[i] /= n;
    return v;
  };
  return {
    id: 'local-bigram', dimensions: dim, network: false,
    async embed(texts) { return texts.map(vec); },
  };
}

export function createApiEmbedding({ endpoint, dim = 2048 }) {
  return {
    id: 'api', dimensions: dim, network: true,
    async embed(texts) {
      const res = await fetch(`${endpoint}/embed`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ input: texts }),
      });
      if (!res.ok) { const e = new Error(`EMBED_HTTP_${res.status}`); e.code = e.code ?? `EMBED_HTTP_${res.status}`; e.status = res.status; throw e; }
      const d = await res.json();
      return d.vectors.map((a) => Float32Array.from(a));
    },
  };
}

export function createNullEmbedding() { return { id: 'none', dimensions: 0, network: false, async embed() { return null; } }; }

export function cosine(a, b) {
  let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s;
}
