import asyncio, json, os, shutil
from playwright.async_api import async_playwright
PROF="/tmp/poc6/prof_mt2"; URL="http://127.0.0.1:8932/mt.html"

async def get(pg,label):
    try: await pg.wait_for_function('window.__result !== undefined', timeout=90000)
    except Exception: print(f"  [{label}] TIMEOUT"); return None
    r = await pg.evaluate('window.__result')
    if r.get('ok'):
        print(f"  [{label}] OK before={r['rowsBefore']} byTag={r['rowsByTag']}")
    else:
        print(f"  [{label}] FAIL {str(r.get('error',''))[:110]}")
    return r

async def main():
    if os.path.exists(PROF): shutil.rmtree(PROF)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(PROF, args=['--no-sandbox'])
        a = await ctx.new_page(); await a.goto(URL+"?mode=write&tag=A"); ra = await get(a,"A rw write")
        b = await ctx.new_page(); await b.goto(URL+"?mode=read&tag=B&am=ro"); rb = await get(b,"B ro read (A 开着)")
        print("\n  只读并发可行:", bool(rb and rb.get('ok')))
        await ctx.close()
        json.dump({"A":ra,"B":rb}, open("/tmp/poc6/mt2.json","w"), ensure_ascii=False, indent=1)
asyncio.run(main())
