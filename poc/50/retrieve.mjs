// One retrieval entry point. The provider is a parameter, never a hard dependency.
import { cosine } from './providers.mjs';

const unigrams = (s) => new Set([...s]);
function jaccard(a, b) {
  const A = unigrams(a), B = unigrams(b);
  let inter = 0; for (const x of A) if (B.has(x)) inter += 1;
  return inter / (A.size + B.size - inter || 1);
}

export function createRetriever({ provider, entries, indexDim = null }) {
  let index = null;
  let retrieval = 'vector';
  let indexError = null;

  // an index is bound to one provider id and one dimension; switching means rebuilding
  async function build() {
    if (!provider || provider.id === 'none') { index = null; retrieval = 'lexical-fallback'; return; }
    if (indexDim !== null && indexDim !== provider.dimensions) {
      const e = new Error('EMBEDDING_DIM_MISMATCH'); e.code = e.code ?? 'EMBEDDING_DIM_MISMATCH'; throw e;
    }
    let vectors;
    try {
      vectors = await provider.embed(entries.map((e) => e.text));
    } catch (e) {
      // availability failure (429 / network) must not stop the system from starting;
      // a configuration error (dimension mismatch) still throws above, on purpose.
      index = null;
      retrieval = 'lexical-fallback';
      indexError = e.code ?? 'PROVIDER_ERROR';
      return;
    }
    index = { providerId: provider.id, dim: provider.dimensions, vectors };
    retrieval = 'vector';
  }

  return {
    async build() { await build(); return this.status(); },
    status() { return { retrieval, providerId: provider?.id ?? 'none', dim: index?.dim ?? 0, indexError }; },
    async topK(query, k = 3) {
      if (retrieval === 'vector') {
        let qv;
        try {
          [qv] = await provider.embed([query]);
        } catch (e) {
          // a provider outage must degrade, and must say so
          retrieval = 'lexical-fallback';
          return { items: lexical(query, k), retrieval: 'lexical-fallback', degraded: e.code ?? 'PROVIDER_ERROR' };
        }
        const scored = entries.map((e, i) => ({ id: e.id, score: cosine(qv, index.vectors[i]) }));
        scored.sort((a, b) => b.score - a.score);
        return { items: scored.slice(0, k), retrieval: 'vector', degraded: null };
      }
      return { items: lexical(query, k), retrieval: 'lexical-fallback', degraded: null };
    },
  };

  function lexical(query, k) {
    return entries
      .map((e) => ({ id: e.id, score: jaccard(query, e.text) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, k);
  }
}
