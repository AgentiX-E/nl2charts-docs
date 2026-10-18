#!/usr/bin/env python3
"""POC-36: 门禁注册表抽取 + G1-G5 校验 + 变异自测。"""
import re, json

T = '/workspace/text2charts-whitepaper/技术设计方案.md'
s = open(T, encoding='utf-8').read()
lines = s.split('\n')

FAMILY = {'DG': ('contract+bench', 'ci:conformance'),
          'FG': ('contract+e2e', 'ci:federation'),
          'UX': ('unit+e2e+manual', 'ci:ui'),
          'P':  ('unit+property', 'ci:unit')}

# ---------- 1) 定义行抽取（三种格式） ----------
DEF_TABLE = re.compile(r'^\|\s*\**(DG|FG|UX)(\d{1,2})\**\s*(\||\s+[^|]+\|)')
DEF_PCODE = re.compile(r'^P(\d{1,2})\s+(.+)$')

gates, dup = {}, []
for ln in lines:
    m = DEF_TABLE.match(ln)
    if m:
        gid = f'{m.group(1)}{m.group(2)}'
        cells = [c.strip() for c in ln.strip('|').split('|')]
        # 排除区间引用行（如 "| **DG1–DG11**（跨层兼容） |"）与汇总行
        if '–' in cells[0] or '-' in cells[0] and re.search(r'\d-\w', cells[0]):
            continue
        crit = ' '.join(c for c in cells[1:] if c)[:400]
        if len(crit) < 8:
            continue
        if gid in gates:
            dup.append(gid)
        gates[gid] = {'id': gid, 'family': m.group(1), 'criterion': crit}
        continue
    m = DEF_PCODE.match(ln)
    if m:
        gid = f'P{m.group(1)}'
        gates.setdefault(gid, {'id': gid, 'family': 'P', 'criterion': m.group(2)[:400]})

# ---------- 2) 孤儿检测（被引用但无定义） ----------
s_plain = re.sub(r'`[^`]*`', '', s)                      # 剔除行内代码示例
s_plain = re.sub(r'\bP0\b(?!\d)', 'SEVERITY', s_plain)   # P0 是严重度，不是门禁
referenced = set(re.findall(r'\b(DG\d{1,2}|FG\d|UX\d|P(?!\d+\-)\d{1,2})\b', s_plain))
defined = set(gates)
orphans = sorted(referenced - defined, key=lambda g: (g[0], int(re.sub(r'\D', '', g))))
ghosts = sorted(defined - referenced)  # 有定义但正文从未引用（罕见）

# ---------- 3) 机读性分类 ----------
for g in gates.values():
    c = g['criterion']
    fam = g['family']
    g['testLayer'], g['ciJob'] = FAMILY[fam]
    g['hasNumber'] = bool(re.search(r'\d', c))
    _th = re.search(r'[≤≥<>]\s*\d[\d.,]*\s*(%|ms|s|pp|条|倍|KB|MB)?', c)
    g['thresholdText'] = _th.group(0).strip() if _th else None
    g['zeroTol'] = bool(re.search(r'=\s*0|0\s*(命中|泄漏|违规|误报)|100%|逐项一致|必须', c))
    g['kind'] = ('threshold' if g['thresholdText'] else
                 'zeroTolerance' if g['zeroTol'] else
                 'numeric' if g['hasNumber'] else 'qualitative')

# ---------- 4) 测试树 + G1-G4 ----------
def make_tree(ids, faults=()):
    body = ["// auto-generated fixture"]
    for gid in ids:
        if ('missing_gate', gid) in faults:
            continue
        body.append(f"describe('[%s] %s', () => {{" % (gid, gid))
        body.append(f"  it('positive: %s 达标时通过', () => {{ expect(1).toBe(1); }});" % gid)
        if ('no_negative', gid) not in faults:
            body.append(f"  it('negative: %s 违反时必须失败', () => {{ expect(1).toBe(2); }});" % gid)
        body.append("});")
    text = "\n".join(body)
    if any(f[0] == 'spurious_id' for f in faults):
        sp = [f[1] for f in faults if f[0] == 'spurious_id'][0]
        text += (f"\ndescribe('[{sp}] typo', () => {{\n"
                 f"  it('positive: x', () => {{}});\n"
                 f"  it('negative: y', () => {{}});\n}});")
    return text

BLOCK = re.compile(r"describe\('\[(\w+)\][^']*',\s*\(\)\s*=>\s*\{(.*?)\n\}\);", re.S)

def check(text, registry_ids):
    pos, neg, declared = {}, {}, set()
    for m in BLOCK.finditer(text):
        gid, inner = m.group(1), m.group(2)
        declared.add(gid)
        pos[gid] = pos.get(gid, 0) + inner.count("it('positive")
        neg[gid] = neg.get(gid, 0) + inner.count("it('negative")
    reg = set(registry_ids)
    return {
        'G1_untested': sorted(reg - declared, key=lambda g: (g[0], int(re.sub(r'\D', '', g)))),
        'G2_unregistered': sorted(declared - reg),
        'G3_no_pos_or_neg': sorted([g for g in reg if pos.get(g, 0) < 1 or neg.get(g, 0) < 1],
                                   key=lambda g: (g[0], int(re.sub(r'\D', '', g)))),
        'parsed_titles': sum(pos.values()) + sum(neg.values()),
    }

ids = sorted(gates, key=lambda g: (g[0], int(re.sub(r'\D', '', g))))
base = check(make_tree(ids), ids)
faults_map = {'missing_gate(FG2)': ('missing_gate', 'FG2'),
              'spurious_id(DG99)': ('spurious_id', 'DG99'),
              'no_negative(P4)': ('no_negative', 'P4')}
mutation = {}
for name, f in faults_map.items():
    r = check(make_tree(ids, faults=[f]), ids)
    hit = [k for k in ('G1_untested', 'G2_unregistered', 'G3_no_pos_or_neg') if r[k]]
    mutation[name] = {'caught': bool(hit), 'by': hit[0] if hit else None,
                      'detail': r[hit[0]][:3] if hit else []}

summary = {
    'defined': len(gates),
    'by_family': {f: sum(1 for g in gates.values() if g['family'] == f) for f in FAMILY},
    'referenced_but_undefined': orphans,
    'defined_but_unreferenced': ghosts,
    'duplicate_rows': sorted(set(dup)),
    'kinds': {k: sum(1 for g in gates.values() if g['kind'] == k)
              for k in ('threshold', 'zeroTolerance', 'numeric', 'qualitative')},
    'qualitative_gates': [g['id'] for g in gates.values() if g['kind'] == 'qualitative'],
    'baseline': {k: (v if k == 'parsed_titles' else len(v)) for k, v in base.items()},
    'mutation': mutation,
    'titles_needed': len(ids) * 2,
}
json.dump({'summary': summary, 'gates': gates}, open('/tmp/poc36_gates.json', 'w'),
          ensure_ascii=False, indent=1)
print(json.dumps(summary, ensure_ascii=False, indent=1))
