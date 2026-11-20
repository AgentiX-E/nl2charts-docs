import asyncio, json, os, shutil
from playwright.async_api import async_playwright

PROF = "/tmp/poc6/prof_mt132"
URL = "http://127.0.0.1:8932/mt.html"

async def get(pg, label):
    try:
        await pg.wait_for_function('window.__result !== undefined', timeout=120000)
    except Exception:
        print(f"  [{label}] TIMEOUT"); return None
    r = await pg.evaluate('window.__result')
    if r.get('ok'):
        print(f"  [{label}] before={r['rowsBefore']} byTag={r['rowsByTag']} sizes={r['sizes']} persisted={r['persisted']}")
    else:
        print(f"  [{label}] FAIL {r.get('error','')[:180]}")
    return r

async def main():
    if os.path.exists(PROF): shutil.rmtree(PROF)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(PROF, args=['--no-sandbox'])
        # 1) 单页写入
        pg1 = await ctx.new_page()
        await pg1.goto(URL + "?mode=write&tag=A")
        r1 = await get(pg1, "tabA write")

        # 2) 第二个标签页并发打开同一库
        pg2 = await ctx.new_page()
        await pg2.goto(URL + "?mode=read&tag=B")
        r2 = await get(pg2, "tabB read (A 仍开着)")

        # 3) B 也写
        pg3 = await ctx.new_page()
        await pg3.goto(URL + "?mode=write&tag=C")
        r3 = await get(pg3, "tabC write (A,B 仍开着)")

        # 4) 关 A、B，重开看最终状态
        await pg1.close(); await pg2.close()
        pg4 = await ctx.new_page()
        await pg4.goto(URL + "?mode=read&tag=D")
        r4 = await get(pg4, "tabD read (A,B,C 已关)")

        await ctx.close()
        json.dump({"A": r1, "B": r2, "C": r3, "D": r4}, open("/tmp/poc6/mt132.json", "w"), ensure_ascii=False, indent=1)

        print("\n===== 判定 =====")
        if r1 and r2:
            print(f"  B 能看到 A 已提交的数据: {'YES' if r2['rowsBefore'] >= 1 else 'NO'}（B before={r2['rowsBefore']}）")
        if r4:
            tags = dict(r4['rowsByTag'])
            print(f"  最终各 tag 计数: {tags}")
            ok = tags.get('A', 0) >= 3 and tags.get('C', 0) >= 3
            print(f"  两个标签页的写入都保留: {'YES' if ok else 'NO'}")

asyncio.run(main())
