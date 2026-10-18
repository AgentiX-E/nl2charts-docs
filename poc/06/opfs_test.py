import asyncio, json, sys, os
from playwright.async_api import async_playwright

PROFILE = "/tmp/poc6/profile"
URL = "http://127.0.0.1:8932/opfs.html"

async def run(tag, label):
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE,
            args=['--no-sandbox', '--enable-features=SharedArrayBuffer'],
        )
        pg = await ctx.new_page()
        errs = []
        pg.on('console', lambda m: errs.append(f"{m.type}: {m.text[:140]}"))
        pg.on('pageerror', lambda e: errs.append(f"pageerror: {str(e)[:200]}"))
        await pg.goto(f"{URL}?tag={tag}")
        try:
            await pg.wait_for_function('window.__result !== undefined', timeout=120000)
        except Exception:
            print(f"[{label}] TIMEOUT")
            print('\n'.join(errs[:8]))
            await ctx.close()
            return None
        res = await pg.evaluate('window.__result')
        await ctx.close()
        print(f"\n===== {label} (tag={tag}) =====")
        print("ok:", res.get("ok"))
        if not res.get("ok"):
            print("ERROR:", res.get("error"))
            print('\n'.join(errs[:6]))
        else:
            print("caps:", json.dumps(res["caps"]))
            print(f"rows: before={res['before']} after={res['after']}")
            for r in res["rows"]:
                print("   ", r)
        return res

async def main():
    # 第 1 次：全新 profile（可能残留，先清）
    import shutil
    if os.path.exists(PROFILE):
        shutil.rmtree(PROFILE)
    r1 = await run("run1", "第1次运行（全新 profile）")
    # 第 2 次：同一 profile，模拟浏览器重启
    r2 = await run("run2", "第2次运行（同 profile = 重启）")

    print("\n===== 结论 =====")
    if r1 and r2 and r1.get("ok") and r2.get("ok"):
        survived = r2["before"] >= 1
        print(f"persist across restart: {'YES' if survived else 'NO'}  (2nd run saw {r2['before']} existing rows)")
        tag1_in_run2 = any(r["tag"] == "run1" for r in r2["rows"])
        print(f"run1 的写入在 run2 可见: {tag1_in_run2}")
        print(f"total rows after 2 runs: {r2['after']} (期望 2)")
    else:
        print("至少一次运行失败，见上")
    json.dump({"run1": r1, "run2": r2}, open("/tmp/poc6/result.json", "w"), ensure_ascii=False, indent=1)

asyncio.run(main())
