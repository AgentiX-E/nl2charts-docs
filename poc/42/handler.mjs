// framework-agnostic admin surface: Request -> Response, zero web-framework imports
export function createAdminHandler(store) {
  return async function handle(req) {
    const url = new URL(req.url);
    const p = url.pathname.replace(/^\/admin\/v1/, '');
    if (req.method === 'GET' && p === '/health') return Response.json({ ok: true, version: store.version });
    if (req.method === 'GET' && p === '/models') return Response.json({ models: store.models });
    if (req.method === 'POST' && p === '/models') {
      const body = await req.json();
      if (!body?.name) return Response.json({ error: 'name required' }, { status: 400 });
      store.models.push(body.name);
      return Response.json({ created: body.name }, { status: 201 });
    }
    return new Response('not found', { status: 404 });
  };
}
