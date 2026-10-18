import json, shutil
from playwright.sync_api import sync_playwright

def series(p, profile, url, n):
    shutil.rmtree(profile, ignore_errors=True)
    ctx = p.chromium.launch_persistent_context(profile, headless=True,
        executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    out = []
    for _ in range(n):
        pg = ctx.new_page(); pg.goto(url, wait_until="load")
        pg.wait_for_function("() => window.__m", timeout=60000)
        out.append(pg.evaluate("window.__m")); pg.close()
    ctx.close()
    return out

BASE = "http://127.0.0.1:8770/e2e.html"
with sync_playwright() as p:
    res = {
      "eh_fresh": series(p, "/tmp/poc32/p_eh", BASE, 3),
      "mvp_fresh": series(p, "/tmp/poc32/p_mvp", BASE + "?engine=mvp", 3),
      "nowasm_fresh": series(p, "/tmp/poc32/p_nw", BASE + "?nowasm=1", 3),
      "nowasm_warm": series(p, "/tmp/poc32/p_nw2", BASE + "?nowasm=1", 4),
    }
    json.dump(res, open("/tmp/poc32_results2.json","w"), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print("==", k)
        for m in v:
            print("  painted=%s wasm=%s query=%s chart=%s aggfetch=%s" % (
                m.get('painted'), m.get('wasm_instantiated'), m.get('query_ms'),
                m.get('chart_compile_ms'), m.get('agg_fetch_ms')))
