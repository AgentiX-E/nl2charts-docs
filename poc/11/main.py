#!/usr/bin/env python3
# POC-11: does a ValueNormalizer close the Node/WASM rowset gap found in POC-1?
# Input: /tmp/poc1/{node_out,wasm_out}.json (same 20 queries, DuckDB 1.5.x both sides)
import json, hashlib
from decimal import Decimal
from collections import Counter

n = json.load(open('/tmp/poc1/node_out.json'))
w = json.load(open('/tmp/poc1/wasm_out.json'))
w = w.get('out', w)

def unwrap(v):
    # WASM double-encodes values: "JSON string containing JSON string"
    for _ in range(6):
        if isinstance(v, str):
            s = v.strip()
            if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
                try:
                    v = json.loads(s)
                    continue
                except Exception:
                    break
            if (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
                try:
                    v = json.loads(s)
                    continue
                except Exception:
                    break
        break
    return v

def canon(x):
    if isinstance(x, dict) and '__t' in x:
        t, v = x['__t'], x['v']
        if t == 'bigint':
            return ('int', int(str(v).strip('"')))
        v = unwrap(v)
        if isinstance(v, dict) and 'value' in v and 'scale' in v:
            val = Decimal(str(v['value']).rstrip('n'))
            return ('dec', str(val.scaleb(-int(v['scale'])).normalize()) if val != 0 else '0')
        if isinstance(v, (int, float)):
            return ('num', repr(float(v)) if isinstance(v, float) else str(v))
        if isinstance(v, str):
            s = v.strip()
            try:
                d = Decimal(s.rstrip('n'))
                return ('dec', str(d.normalize()) if d != 0 else '0')
            except Exception:
                return ('str', s)
        if isinstance(v, list):
            return ('list', tuple(canon(i) if isinstance(i, dict) else ('raw', str(i)) for i in v))
        if isinstance(v, dict):
            return ('map', tuple(sorted((k, str(canon(y) if isinstance(y, dict) else y)) for k, y in v.items())))
        return ('obj', str(v))
    if isinstance(x, (int, float)):
        return ('num', repr(float(x)))
    s = str(x)
    try:
        d = Decimal(s)
        return ('dec', str(d.normalize()) if d != 0 else '0')
    except Exception:
        return ('str', s)

def rows_of(q):
    if 'error' in q: return None
    return [tuple(canon(c) for c in row) for row in q.get('rows', [])]

def hash_rows(rows, cols):
    payload = json.dumps({'cols': cols, 'rows': sorted(sorted(map(str, r)) for r in rows)}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]

same_raw = same_norm = 0
detail = []
for k in n:
    a, b = n[k], w.get(k, {})
    raw_same = (a == b)
    ra, rb = rows_of(a), rows_of(b)
    cols_a, cols_b = a.get('cols'), b.get('cols')
    if ra is None or rb is None:
        norm_same = ('error' in a) == ('error' in b)
    else:
        norm_same = (Counter(ra) == Counter(rb)) and (cols_a == cols_b)
    same_raw += raw_same
    same_norm += bool(norm_same)
    if not norm_same:
        detail.append({'q': k, 'cols': [cols_a, cols_b],
                       'node': [list(map(str, r)) for r in (ra or [])][:3],
                       'wasm': [list(map(str, r)) for r in (rb or [])][:3],
                       'node_err': a.get('error'), 'wasm_err': b.get('error')})

print(f"raw equality     : {same_raw}/20")
print(f"normalized eq.   : {same_norm}/20")
print(f"residual diffs   : {len(detail)}")
for d in detail:
    print(json.dumps(d, ensure_ascii=False)[:600])

# hash stability check: same normalized content -> same hash regardless of engine/type names
h_ok = 0
for k in n:
    ra, rb = rows_of(n[k]), rows_of(w.get(k, {}))
    if ra is not None and rb is not None and Counter(ra) == Counter(rb):
        if hash_rows(ra, n[k].get('cols')) == hash_rows(rb, w[k].get('cols')): h_ok += 1
print(f"hash agreement on normalized rows: {h_ok}")

json.dump({'raw': same_raw, 'normalized': same_norm, 'residual': detail,
           'hash_ok': h_ok}, open('/tmp/poc11_results.json','w'), ensure_ascii=False, indent=1)
