import json, shutil, statistics
from playwright.sync_api import sync_playwright
URL = "http://127.0.0.1:8770/e2e.html"

def run(p, profile, n, label):
    shutil.rmtree(profile, ignore_errors=True)
    ctx = p.chromium.launch_persistent_context(profile, headless=True,
        executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    outs = []
    for i in range(n):
        pg = ctx.new_page()
        pg.goto(URL, wait_until="load")
        pg.wait_for_function("() => window.__m", timeout=60000)
        outs.append(pg.evaluate("window.__m"))
        pg.close()
    ctx.close()
    return outs

with sync_playwright() as p:
    cold = run(p, "/tmp/poc32/prof_cold", 3, "cold")
    warm = run(p, "/tmp/poc32/prof_warm", 4, "warm")   # 第 1 次是冷的，后 3 次走 HTTP 缓存
    res = {"cold": cold, "warm_series": warm}
    json.dump(res, open("/tmp/poc32_results.json","w"), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print("==", k)
        for m in v:
            print("  painted=%s wasm=%s fetch=%s query=%s chart=%s fcp=%s" % (
                m.get('painted'), m.get('wasm_instantiated'), m.get('fetch_ms'),
                m.get('query_ms'), m.get('chart_compile_ms'), m.get('fcp')))
