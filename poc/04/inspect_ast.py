#!/usr/bin/env python3
"""POC-4: check the four specific claims against the raw AST of each version."""
import duckdb, json, sys

def ast(sql):
    raw = duckdb.sql("select json_serialize_sql(?)", params=[sql]).fetchone()[0]
    return json.loads(raw)

def find(node, pred, path=''):
    out = []
    if isinstance(node, dict):
        if pred(node): out.append((path, node))
        for k, v in node.items(): out += find(v, pred, f'{path}/{k}')
    elif isinstance(node, list):
        for v in node: out += find(v, pred, f'{path}[]')
    return out

R = {}
# 1) SET_OPERATION_NODE keys
for sql in ["SELECT a FROM t UNION SELECT a FROM u"]:
    d = ast(sql)
    n = find(d, lambda x: x.get('type') == 'SET_OPERATION_NODE')
    R['setop'] = {'keys': sorted(n[0][1].keys()) if n else None, 'has_children': bool(n and 'children' in n[0][1])}
    if n and 'children' in n[0][1]:
        R['setop']['children_len'] = len(n[0][1]['children'])

# 2) BASE_TABLE keys (catalog_name / schema_name present from which version?)
d = ast("SELECT * FROM t")
b = find(d, lambda x: x.get('type') == 'BASE_TABLE')
R['base_table'] = {'keys': sorted(b[0][1].keys()) if b else None,
                   'has_catalog': bool(b and 'catalog_name' in b[0][1]),
                   'has_schema': bool(b and 'schema_name' in b[0][1])}

# 3) CTE name appears as BASE_TABLE?
d = ast("WITH c AS (SELECT * FROM t) SELECT * FROM c")
bt = [n[1].get('table_name') for n in find(d, lambda x: x.get('type') == 'BASE_TABLE')]
R['cte_as_base_table'] = sorted(bt)

# 4) AT (VERSION => 1) — where does the version live?
try:
    d = ast("SELECT * FROM t AT (VERSION => 1)")
    bt = find(d, lambda x: x.get('type') == 'BASE_TABLE')
    R['at_version'] = {'base_table_keys': sorted(bt[0][1].keys()) if bt else None,
                       'at_clause': bt[0][1].get('at_clause') if bt else None}
except Exception as e:
    R['at_version'] = {'error': str(e)[:120]}

# 5) type_info: CAST to a DECIMAL / custom type
for sql in ["SELECT CAST(a AS DECIMAL(10,2)) FROM t", "SELECT CAST(a AS STRUCT(x INT)) FROM t"]:
    d = ast(sql)
    ti = find(d, lambda x: 'type_info' in x if isinstance(x, dict) else False)
    R.setdefault('type_info', {})[sql] = [
        {'path': p, 'keys': sorted(v['type_info'].keys()) if isinstance(v.get('type_info'), dict) else None,
         'type_info': v.get('type_info')}
        for p, v in ti][:2]

print(json.dumps({'version': duckdb.__version__, **R}, ensure_ascii=False, indent=1))
json.dump({'version': duckdb.__version__, **R}, open(f'inspect-{duckdb.__version__}.json', 'w'), ensure_ascii=False, indent=1)
