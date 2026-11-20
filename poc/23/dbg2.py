from playwright.sync_api import sync_playwright
import json
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context("/tmp/poc23/profile3", headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    pg.goto("http://127.0.0.1:8765/opfs.html")
    pg.wait_for_function("() => window.__done", timeout=90000)
    print(json.dumps(pg.evaluate("window.__done")))
    ctx.close()
