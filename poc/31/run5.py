import json, shutil, time
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8767/conc.html"
with sync_playwright() as p:
    shutil.rmtree("/tmp/poc31/prof_st", ignore_errors=True)
    ctx = p.chromium.launch_persistent_context("/tmp/poc31/prof_st", headless=True,
            executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    a = ctx.new_page(); a.goto(f"{BASE}?tab=A&mode=lock&db=st.db", wait_until="load")
    a.wait_for_function("() => window.__done", timeout=120000)
    print("A(base 300):", [x for x in a.evaluate("window.__done")['steps'] if x[0] in ('count_reopen','bytes')])
    h = ctx.new_page(); h.goto(f"{BASE}?tab=H&mode=holdwrites&db=st.db&hold=12000", wait_until="load")
    time.sleep(3.0)
    r = ctx.new_page(); r.goto(f"{BASE}?tab=R&mode=reader&ro=1&db=st.db", wait_until="load")
    r.wait_for_function("() => window.__done", timeout=40000)
    print("R(reader while uncommitted):", json.dumps(r.evaluate("window.__done")['steps'], ensure_ascii=False)[:300])
    ctx.close()
