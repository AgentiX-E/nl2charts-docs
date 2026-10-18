from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    pg = b.new_page()
    pg.on("console", lambda m: print("CONSOLE", m.type, m.text[:200]))
    pg.on("pageerror", lambda e: print("PAGEERROR", str(e)[:300]))
    pg.goto("http://127.0.0.1:8765/opfs.html")
    pg.wait_for_timeout(8000)
    print("DONE?", pg.evaluate("window.__done || null"))
    b.close()
