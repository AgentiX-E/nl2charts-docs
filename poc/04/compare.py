#!/usr/bin/env python3
"""POC-4: diff structural fingerprints across three DuckDB versions."""
import json, collections

V = ['1.3.2', '1.4.5', '1.5.6']
data = {v: json.load(open(f'fp-{v}.json'))['results'] for v in V}
ids = sorted(data[V[0]], key=int)

same, diff = [], []
for i in ids:
    sets = {v: set(data[v][i]['fp']) for v in V}
    if all(data[v][i]['error'] for v in V):
        same.append(i)                      # all three reject it identically
        continue
    if any(data[v][i]['error'] for v in V):
        diff.append((i, 'error-state-mismatch', {})); continue
    if len(set(frozenset(s) for s in sets.values())) == 1:
        same.append(i)
    else:
        base, last = sets[V[0]], sets[V[-1]]
        diff.append((i, 'fingerprint', {'removed': sorted(base - last), 'added': sorted(last - base)}))

print(f'total={len(ids)} identical={len(same)} differing={len(diff)}')

# classify each difference: added field / removed field / renamed
report = []
for i, kind, d in diff:
    if kind != 'fingerprint':
        report.append({'id': i, 'sql': data[V[-1]][i]['sql'], 'kind': kind}); continue
    rem = [x.split('|', 1)[1] for x in d['removed'] if '|keys=' in x]
    add = [x.split('|', 1)[1] for x in d['added'] if '|keys=' in x]
    paths_rem = [x.split('|')[0] for x in d['removed'] if '|keys=' in x]
    report.append({
        'id': i, 'sql': data[V[-1]][i]['sql'],
        'removed_keys': sorted(set(rem))[:3], 'added_keys': sorted(set(add))[:3],
        'removed_paths': sorted(set(paths_rem))[:3],
        'danger_removed_node': any('|type=' in x for x in d['removed']),
    })
for r in report:
    print(json.dumps(r, ensure_ascii=False))

json.dump({'identical': len(same), 'total': len(ids), 'diffs': report}, open('compare.json', 'w'), ensure_ascii=False, indent=1)
