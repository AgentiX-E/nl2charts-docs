// Browser-side tier. Zero node imports: only fetch and in-memory state.
export function createHttpTier(cfg) {
  const endpoint = cfg.endpoint.replace(/\/$/, '');
  const state = { snapshotId: null, rows: 0, loaded: 0 };

  async function call(path, init) {
    let res;
    try {
      res = await fetch(`${endpoint}${path}`, init);
    } catch (e) {
      const err = new Error('TIER_UNAVAILABLE');
      err.code = 'TIER_UNAVAILABLE';
      err.cause = e;
      throw err;                              // never degrade silently
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const err = new Error(body.error ?? `HTTP_${res.status}`);
      err.code = body.error ?? `HTTP_${res.status}`;
      err.status = res.status;
      throw err;
    }
    return res;
  }

  return {
    async describe() {
      const res = await call('/describe', { method: 'GET' });
      const d = await res.json();
      state.snapshotId = d.snapshotId;
      state.rows = d.tiers[0].rows;
      return d;
    },
    /** detect what is missing locally, then pull exactly that from upstream */
    async backfill(sql, localRows) {
      const need = state.rows - localRows;
      if (need <= 0) return { fetched: 0, reason: 'local-complete' };
      const res = await call('/fetch', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ sql, partition: 0 }),
      });
      // snapshot alignment: a mismatched snapshot is a hard error, not a merge
      const snap = res.headers.get('x-tier-snapshot');
      if (snap && state.snapshotId && snap !== state.snapshotId) {
        const err = new Error('SNAPSHOT_MISMATCH');
        err.code = 'SNAPSHOT_MISMATCH';
        throw err;
      }
      const d = await res.json();
      state.loaded = d.rows.length;
      return { fetched: d.rows.length, snapshotId: d.snapshotId, rows: d.rows };
    },
    get state() { return { ...state }; },
  };
}
