import json, sys, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8767/conc.html"

def scenario(p, name, mode, db, pages=2):
    profile = f"/tmp/poc31/prof_{name}"
    import shutil, os
    shutil.rmtree(profile, ignore_errors=True)
    ctx = p.chromium.launch_persistent_context(profile, headless=True,
            executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    ps = []
    for i in range(pages):
        pg = ctx.new_page()
        pg.goto(f"{BASE}?tab=T{i}&mode={mode}&db={db}.db", wait_until="load")
        ps.append(pg)
    # 让两个页面都完成 wasm 实例化后再一起进入栅栏（每页自行对齐绝对时间）
    time.sleep(0.2)
    res = []
    for pg in ps:
        try:
            pg.wait_for_function("() => window.__done", timeout=120000)
            res.append(pg.evaluate("window.__done"))
        except Exception as e:
            res.append({"tab": "?", "error": str(e)[:160]})
    ctx.close()
    return res

with sync_playwright() as p:
    out = {}
    out['nolock'] = scenario(p, 'nolock', 'nolock', 'nl')
    out['lock'] = scenario(p, 'lock', 'lock', 'lk')
    out['ifavail'] = scenario(p, 'ifavail', 'ifavail', 'fa')
    json.dump(out, open('/tmp/poc31_results.json', 'w'), ensure_ascii=False, indent=1)
    for k, v in out.items():
        print('='*20, k)
        for tab in v:
            print(' ', tab.get('tab'), '->', json.dumps(tab.get('steps') or tab, ensure_ascii=False)[:700])
