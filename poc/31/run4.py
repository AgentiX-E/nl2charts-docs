import json, shutil, time
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8767/conc.html"
with sync_playwright() as p:
    shutil.rmtree("/tmp/poc31/prof_ro", ignore_errors=True)
    ctx = p.chromium.launch_persistent_context("/tmp/poc31/prof_ro", headless=True,
            executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    # A: 先建库并持有（RW）
    a = ctx.new_page(); a.goto(f"{BASE}?tab=A&mode=lock&db=ro.db", wait_until="load")
    a.wait_for_function("() => window.__done", timeout=120000)
    print("A(writer):", json.dumps(a.evaluate("window.__done")['steps'], ensure_ascii=False)[:300])
    # B: 同时开 RW 的 leader 与 RO 的 reader
    h = ctx.new_page(); h.goto(f"{BASE}?tab=H&mode=ifavail&db=ro.db&hold=12000", wait_until="load")
    time.sleep(1.2)
    h_steps = h.evaluate("window.__done || null")
    print("H(holder) mid:", json.dumps(h_steps, ensure_ascii=False)[:160])
    r = ctx.new_page(); r.goto(f"{BASE}?tab=R&mode=reader&ro=1&db=ro.db", wait_until="load")
    r.wait_for_function("() => window.__done", timeout=40000)
    print("R(reader):", json.dumps(r.evaluate("window.__done")['steps'], ensure_ascii=False)[:400])
    ctx.close()
