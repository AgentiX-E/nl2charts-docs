import json
n = json.load(open('/tmp/poc1/node_out.json'))
w = json.load(open('/tmp/poc1/wasm_out.json'))
w = w['out']
print(f"node queries={len(n)} wasm queries={len(w)}\n")
same, diff = [], []
for k in n:
    a, b = n[k], w.get(k, {})
    if a == b: same.append(k)
    else: diff.append(k)

print(f"完全一致: {len(same)} | 有差异: {len(diff)}\n")
for k in diff:
    a, b = n[k], w.get(k, {})
    print(f"=== {k}")
    if 'error' in a or 'error' in b:
        print(f"  node: {a.get('error','(ok)')}")
        print(f"  wasm: {b.get('error','(ok)')}")
        continue
    if a.get('types') != b.get('types'):
        print(f"  types node={a.get('types')}")
        print(f"        wasm={b.get('types')}")
    if a.get('rows') != b.get('rows'):
        print(f"  rows node={json.dumps(a.get('rows'),ensure_ascii=False)[:300]}")
        print(f"       wasm={json.dumps(b.get('rows'),ensure_ascii=False)[:300]}")
    print()
