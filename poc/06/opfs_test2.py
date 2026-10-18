import asyncio, json, sys, os, shutil, subprocess
from playwright.async_api import async_playwright

WEB = "/tmp/poc6/web"

def stage(dist, label):
    """把某个 wasm 版本的 dist 拷进 web 目录"""
    for f in ["duckdb-browser.mjs", "duckdb-browser-eh.worker.js", "duckdb-eh.wasm",
              "duckdb-browser-mvp.worker.js", "duckdb-mvp.wasm"]:
        src = os.path.join(dist, f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(WEB, f))
    print(f"[stage] {label}")

async def once(profile, tag, label):
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(profile, args=['--no-sandbox'])
        pg = await ctx.new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:160]))
        await pg.goto(f"http://127.0.0.1:8932/opfs2.html?tag={tag}")
        try:
            await pg.wait_for_function('window.__result !== undefined', timeout=120000)
        except Exception:
            print(f"  [{label}] TIMEOUT"); print('  ' + '\n  '.join(errs[:5]))
            await ctx.close(); return None
        res = await pg.evaluate('window.__result')
        await ctx.close()
        if not res.get('ok'):
            print(f"  [{label}] FAIL: {res.get('error','')[:200]}")
            return res
        print(f"  [{label}] engine={res['engine']} before={res['before']} after={res['after']}")
        print(f"     opfs@write: {json.dumps(res['opfsImmediate'])[:220]}")
        print(f"     opfs@close: {json.dumps(res['opfsAfterClose'])[:220]}")
        return res

async def trial(name, dist, label):
    stage(dist, label)
    prof = f"/tmp/poc6/prof_{name}"
    if os.path.exists(prof): shutil.rmtree(prof)
    print(f"\n===== {label} =====")
    r1 = await once(prof, "run1", "run1")
    r2 = await once(prof, "run2", "run2(reopen)")
    if r1 and r2 and r1.get('ok') and r2.get('ok'):
        surv = r2['before'] >= 1
        print(f"  → 跨重启持久化: {'YES' if surv else 'NO'} (2nd before={r2['before']})")
        return {"label": label, "persist": surv, "r1": r1, "r2": r2}
    return {"label": label, "persist": None, "r1": r1, "r2": r2}

async def main():
    results = []
    results.append(await trial("v57", "/tmp/poc1/node_modules/@duckdb/duckdb-wasm/dist", "dev57 (npm latest)"))
    results.append(await trial("v65", "/tmp/w65/node_modules/@duckdb/duckdb-wasm/dist", "dev65 (npm next)"))
    results.append(await trial("v132", "/tmp/w132/node_modules/@duckdb/duckdb-wasm/dist", "1.32.0 (stable)"))
    json.dump(results, open("/tmp/poc6/result2.json", "w"), ensure_ascii=False, indent=1)
    print("\n===== 汇总 =====")
    for r in results:
        print(f"  {r['label']:26s} persist={r['persist']}")

asyncio.run(main())
