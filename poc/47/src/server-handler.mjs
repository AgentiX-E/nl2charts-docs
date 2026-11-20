// Runs on the server only. Framework-agnostic, same shape as core/admin.
// It owns the credentials; the browser never sees a connection string.
import { assertReadOnly } from './guard.mjs';
import { createNodeEngine } from './engine-node.mjs';

export function createTierHandler(opts) {
  const engine = opts.engine ?? createNodeEngine();
  const version = opts.version ?? 1;
  const snapshot = opts.snapshotId ?? 'snap-0001';

  return async function handle(req) {
    const url = new URL(req.url);
    const p = url.pathname.replace(/^\/tier\/v1/, '');

    if (req.method === 'GET' && p === '/describe') {
      return Response.json({
        version,
        snapshotId: snapshot,
        // what the browser is allowed to know: capability, not credentials
        capabilities: { pushdown: 'remote', formats: ['json'], maxPartitionRows: 500 },
        tiers: [{ role: 'authoritative', kind: 'node-engine', rows: 1000 }],
      });
    }

    if (req.method === 'POST' && p === '/fetch') {
      let body;
      try { body = await req.json(); } catch { return Response.json({ error: 'BAD_JSON' }, { status: 400 }); }
      if (!body?.sql) return Response.json({ error: 'SQL_REQUIRED' }, { status: 400 });
      try {
        assertReadOnly(body.sql);              // guard runs BEFORE the engine
      } catch (e) {
        return Response.json({ error: e.code }, { status: 403 });
      }
      const rows = await engine.query(body.sql);
      return Response.json(
        { snapshotId: snapshot, partition: body.partition ?? 0, rows },
        { headers: { 'x-tier-snapshot': snapshot } },
      );
    }

    return new Response('not found', { status: 404 });
  };
}
