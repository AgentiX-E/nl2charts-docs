from playwright.sync_api import sync_playwright
import json
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    for name in ("own", "rjsf"):
        vals = []
        for _ in range(5):
            pg = b.new_page(); pg.goto(f"http://127.0.0.1:8766/{name}.html")
            pg.wait_for_function("() => window.__t", timeout=20000)
            vals.append(pg.evaluate("window.__t")); pg.close()
        print(name, json.dumps(vals), "median", sorted(vals)[2])
    b.close()
