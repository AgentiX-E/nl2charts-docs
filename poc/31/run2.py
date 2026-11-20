import json, shutil, time
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8767/conc.html"
with sync_playwright() as p:
    shutil.rmtree("/tmp/poc31/prof_fo", ignore_errors=True)
    ctx = p.chromium.launch_persistent_context("/tmp/poc31/prof_fo", headless=True,
            executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    leader = ctx.new_page(); leader.goto(f"{BASE}?tab=L&mode=ifavail&db=fo.db&hold=20000", wait_until="load")
    time.sleep(0.8)
    follower = ctx.new_page(); follower.goto(f"{BASE}?tab=F&mode=wait&db=fo.db", wait_until="load")
    # 等 leader 真正拿到锁
    leader.wait_for_function("() => (window.__done||{}).steps && window.__done.steps.some(s=>s[0]==='lock')", timeout=30000)
    t_close = time.time()
    leader.close()
    follower.wait_for_function("() => window.__done", timeout=40000)
    res = follower.evaluate("window.__done")
    # 计算接管延迟
    step = [x for x in res['steps'] if x[0] == 'lock']
    print("follower steps:", json.dumps(res['steps'], ensure_ascii=False)[:600])
    if step and 'leader-after-wait@' in str(step[0][1]):
        ms = int(str(step[0][1]).split('@')[1]) - int(t_close*1000)
        print(f"failover latency ~ {ms} ms after leader close")
    ctx.close()
