#!/usr/bin/env python3
"""POC-4: structural fingerprint of json_serialize_sql() output for one DuckDB build."""
import duckdb, json, sys, collections

def walk(node, path, fp):
    if isinstance(node, dict):
        t = node.get('type')
        keys = ','.join(sorted(node.keys()))
        fp.add(f"{path}|type={t}")
        fp.add(f"{path}|keys={keys}")
        for k, v in node.items():
            walk(v, f"{path}/{k}", fp)
    elif isinstance(node, list):
        for v in node:
            walk(v, f"{path}[]", fp)

def analyse(sql):
    try:
        raw = duckdb.sql("select json_serialize_sql(?)", params=[sql]).fetchone()[0]
        d = json.loads(raw)
    except Exception as e:
        return {'error': True, 'msg': str(e)[:160], 'fp': []}
    if d.get('error'):
        return {'error': True, 'msg': str(d.get('error_message'))[:160], 'fp': []}
    fp = set()
    walk(d, '', fp)
    return {'error': False, 'msg': None, 'fp': sorted(fp)}

samples = json.load(open('samples.json'))
out = {'version': duckdb.__version__, 'results': {}}
for s in samples:
    out['results'][s['id']] = {'sql': s['sql'], 'cat': s['cat'], **analyse(s['sql'])}
json.dump(out, open(f"fp-{duckdb.__version__}.json", 'w'), ensure_ascii=False, indent=1)
errs = [k for k, v in out['results'].items() if v['error']]
print(duckdb.__version__, 'samples', len(samples), 'errors', len(errs), 'ok', len(samples) - len(errs))
