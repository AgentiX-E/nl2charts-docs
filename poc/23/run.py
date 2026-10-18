import json, time
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765"

def get(page, key, timeout=90):
    page.wait_for_function(f"() => window.{key}", timeout=timeout*1000)
    return page.evaluate(f"window.{key}")

with sync_playwright() as p:
    # --- persistent profile: write then reload ---
    ctx = p.chromium.launch_persistent_context("/tmp/poc23/profile", headless=True,
            executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    t0=time.time(); page.goto(URL + "/opfs.html"); r1 = get(page, "__done"); t1=time.time()
    print("RUN1", json.dumps(r1), f"{t1-t0:.1f}s")
    page.reload(); r2 = get(page, "__done")
    print("RELOAD", json.dumps(r2))

    # --- fresh profile: isolation check ---
    ctx2 = p.chromium.launch_persistent_context("/tmp/poc23/profile2", headless=True,
            executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    p2 = ctx2.pages[0] if ctx2.pages else ctx2.new_page()
    p2.goto(URL + "/opfs.html"); r3 = get(p2, "__done")
    print("FRESH_PROFILE", json.dumps(r3))

    # --- chart timing: 3 reloads on fresh page ---
    for i in range(3):
        pg = ctx.new_page(); pg.goto(URL + "/chart.html")
        c = get(pg, "__chart", timeout=30)
        print("CHART", i, json.dumps(c))
        pg.close()
    ctx.close(); ctx2.close()
