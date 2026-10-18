#!/usr/bin/env python3
# POC-11b: type-directed ValueNormalizer with per-engine adapters
# Goal: raw 2/20 -> generic 13/20 -> type-directed ?/20
import json, hashlib
from decimal import Decimal, localcontext
from collections import Counter
from datetime import date, datetime, timezone

n = json.load(open('/tmp/poc1/node_out.json'))
w = json.load(open('/tmp/poc1/wasm_out.json'))
w = w.get('out', w)

def unwrap(v):
    for _ in range(8):
        if isinstance(v, str):
            s = v.strip()
            if (s.startswith('"') and s.endswith('"')) or (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
                try:
                    v = json.loads(s); continue
                except Exception:
                    break
        break
    return v

def dec_str(d):
    d = Decimal(d)
    if not d.is_finite(): return 'NaN' if d.is_nan() else ('Infinity' if d > 0 else '-Infinity')
    if d == 0: return '0'
    s = format(d.normalize(), 'f')
    return s

def norm_num(d): return ('dec', dec_str(d))

def node_cell(v, typ):
    if isinstance(v, dict) and v.get('__t') == 'bigint':
        return norm_num(Decimal(str(v['v'])))
    if isinstance(v, dict) and v.get('__t') == 'num':
        x = str(v['v'])
        return ('dec', x) if x in ('Infinity', '-Infinity', 'NaN') else norm_num(Decimal(x))
    if isinstance(v, dict) and v.get('__t') == 'str':
        return ('str', str(v['v']))
    if isinstance(v, dict) and v.get('__t') == 'obj':
        o = unwrap(v['v'])
        if isinstance(o, dict) and 'width' in o:            # DECIMAL
            return norm_num(Decimal(str(o['value']).rstrip('n')).scaleb(-int(o['scale'])))
        if isinstance(o, dict) and 'micros' in o and 'months' not in o and 'days' not in o:
            return ('ts', str(int(str(o['micros']).rstrip('n'))))     # micros, UTC
        if isinstance(o, dict) and 'days' in o and 'months' not in o:
            return ('date', str(date(1970,1,1) + __import__('datetime').timedelta(days=int(o['days']))))
        if isinstance(o, dict) and {'months','days','micros'} <= set(o):
            return ('interval', f"{int(o['months'])}:{int(o['days'])}:{int(str(o['micros']).rstrip('n'))}")
        if isinstance(o, dict) and 'entries' in o:
            e = o['entries']
            return ('struct', tuple(sorted((k, json.dumps(x, sort_keys=True, ensure_ascii=False)) for k, x in e.items())))
        if isinstance(o, dict) and 'items' in o:
            return ('list', tuple(canon_scalar(x) for x in o['items']))
        if isinstance(o, list):
            return ('list', tuple(canon_scalar(x) for x in o))
        if isinstance(o, dict):
            return ('struct', tuple(sorted((k, json.dumps(x, sort_keys=True, ensure_ascii=False)) for k, x in o.items())))
        return canon_scalar(o)
    return canon_scalar(v)

def wasm_cell(v, typ):
    typ = typ or ''
    if isinstance(v, dict) and v.get('__t') == 'str':
        return ('str', str(unwrap(v['v'])))
    if isinstance(v, dict) and v.get('__t') == 'obj':
        o0 = unwrap(v['v'])
        if isinstance(o0, dict) and '__t' in o0:
            return wasm_cell(o0, typ)
    if isinstance(v, dict) and v.get('__t') == 'bigint':
        return norm_num(Decimal(str(v['v'])))
    if isinstance(v, dict) and v.get('__t') == 'num':
        x = v['v']
        # JS numbers: timestamps in ms, dates in ms, decimals unscaled string kept in type
        if typ.startswith('Timestamp'):
            return ('ts', str(int(round(float(x)*1000))))          # ms -> micros
        if typ.startswith('Date32'):
            days = int(round(float(x)/86400000))
            return ('date', str(date(1970,1,1) + __import__('datetime').timedelta(days=days)))
        return norm_num(Decimal(str(x)))
    if isinstance(v, dict) and v.get('__t') == 'obj':
        o = unwrap(v['v'])
        # Decimal[N e+S] carries scale in the type
        if typ.startswith('Decimal['):
            import re as _re
            m = _re.search(r"e([+-]?\d+)\]", typ)
            scale = int(m.group(1)) if m else 0
            return norm_num(Decimal(str(o)).scaleb(-scale))
        if isinstance(o, dict) and set(o) == {'0','1','2','3'}:
            return ('interval', f"{o['0']}:{o['1']}:{Decimal(str(o['2'])).scaleb(-3).__int__() if False else int(Decimal(str(o['2'])))}")
        if isinstance(o, dict):
            return ('struct', tuple(sorted((k, json.dumps(x, sort_keys=True, ensure_ascii=False)) for k, x in o.items())))
        if isinstance(o, list):
            return ('list', tuple(canon_scalar(x) for x in o))
        return canon_scalar(o)
    if isinstance(v, (int,float)):
        if typ.startswith('Timestamp'): return ('ts', str(int(v*1000)))
        if typ.startswith('Date32'): return ('date', str(date(1970,1,1)+__import__('datetime').timedelta(days=int(v/86400000))))
        return norm_num(Decimal(str(v)))
    return canon_scalar(v)

def canon_scalar(x):
    if isinstance(x, bool): return ('bool', str(x))
    if isinstance(x, (int,)): return norm_num(Decimal(x))
    if isinstance(x, float): return norm_num(Decimal(str(x)))
    if x is None: return ('null', '')
    s = str(x)
    try:
        return norm_num(Decimal(s))
    except Exception:
        return ('str', s)

def canon_json(s):
    try:
        o = json.loads(s)
    except Exception:
        try:
            import ast
            o = ast.literal_eval(s)
        except Exception:
            return ('str', s)
    return ('json', json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(',', ':')))

def norm_query(q, engine):
    if 'error' in q: return None
    cols = q.get('cols', [])
    types = q.get('types', [])
    rows = []
    for row in q.get('rows', []):
        out = []
        for i, cell in enumerate(row):
            typ = types[i] if i < len(types) else ''
            c = node_cell(cell, typ) if engine == 'node' else wasm_cell(cell, typ)
            if c[0] == 'str' and c[1][:1] in ('{', '[') and c[1][-1:] in ('}', ']'):
                c = canon_json(c[1])
            out.append(c)
        rows.append(tuple(out))
    return cols, rows

def hq(cols, rows):
    payload = json.dumps({'cols': cols, 'rows': sorted(json.dumps(list(map(list, r)), ensure_ascii=False) for r in rows)},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]

same = 0; residual = []; hash_ok = 0
for k in n:
    a = norm_query(n[k], 'node'); b = norm_query(w.get(k, {}), 'wasm')
    if a is None or b is None:
        ok = (a is None) and (b is None)
    else:
        ok = a[0] == b[0] and Counter(a[1]) == Counter(b[1])
    same += bool(ok)
    if not ok:
        residual.append({'q': k, 'node': str(a)[:400], 'wasm': str(b)[:400]})
    else:
        if a and b:
            if hq(*a) == hq(*b): hash_ok += 1
            else: print("HASH-DIFF:", k)

print(f"type-directed normalization: {same}/20")
print(f"hash agreement             : {hash_ok}/20")
for r in residual: print(json.dumps(r, ensure_ascii=False)[:700])
json.dump({'normalized': same, 'hash_ok': hash_ok, 'residual': residual}, open('/tmp/poc11_results_v2.json','w'), ensure_ascii=False, indent=1)
