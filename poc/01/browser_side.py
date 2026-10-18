import asyncio, json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        pg = await b.new_page()
        errs = []
        pg.on('console', lambda m: errs.append(f"{m.type}: {m.text[:150]}"))
        pg.on('pageerror', lambda e: errs.append(f"pageerror: {str(e)[:200]}"))
        await pg.goto('http://127.0.0.1:8931/index.html')
        try:
            await pg.wait_for_function('window.__result !== undefined', timeout=90000)
        except Exception as e:
            print('TIMEOUT waiting for result'); print('\n'.join(errs[:10])); await b.close(); return
        res = await pg.evaluate('window.__result')
        await b.close()
        open('/tmp/poc1/wasm_out.json','w').write(json.dumps(res, ensure_ascii=False, indent=1))
        print('ok:', res.get('ok'), '| log:', res.get('log'))
        if not res.get('ok'):
            print('ERROR:', res.get('error'))
            print('\n'.join(errs[:8]))
        else:
            print('queries:', len(res['out']))

asyncio.run(main())
