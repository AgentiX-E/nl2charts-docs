import json, shutil, time
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8767/conc.html"
with sync_playwright() as p:
    shutil.rmtree("/tmp/poc31/prof_fo2", ignore_errors=True)
    ctx = p.chromium.launch_persistent_context("/tmp/poc31/prof_fo2", headless=True,
            executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    leader = ctx.new_page(); leader.goto(f"{BASE}?tab=L&mode=ifavail&db=fo2.db&hold=20000", wait_until="load")
    time.sleep(1.5)
    print("leader steps:", json.dumps(leader.evaluate("window.__done || null"), ensure_ascii=False)[:300])
    follower = ctx.new_page(); follower.goto(f"{BASE}?tab=F&mode=wait&db=fo2.db", wait_until="load")
    time.sleep(2.0)
    print("follower mid:", json.dumps(follower.evaluate("window.__done || null"), ensure_ascii=False)[:200])
    # 用导航离开释放锁（模拟崩溃/关闭）
    t0 = time.time(); leader.goto("about:blank")
    try:
        follower.wait_for_function("() => window.__done", timeout=40000)
        res = follower.evaluate("window.__done")
        print("follower:", json.dumps(res['steps'], ensure_ascii=False)[:500])
        st = [x for x in res['steps'] if x[0]=='lock']
        if st: print("failover latency ms ~", int(st[0][1].split('@')[1]) - int(t0*1000))
    except Exception as e:
        print("follower timeout:", str(e)[:100])
    ctx.close()
