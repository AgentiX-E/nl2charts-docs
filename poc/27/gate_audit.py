#!/usr/bin/env python3
"""POC-27: 门禁可追溯性审计
从技术设计方案中抽取所有门禁编号，检查每条是否有：
  (a) 判据（含数字/必须/禁止/一致 等可判定词）
  (b) 测试层归属（单元/契约/E2E/基准/人工）
  (c) WBS 任务关联（T0..T6 段落中被提及）
输出孤儿门禁清单。
"""
import re, json, sys

TECH = '/workspace/text2charts-whitepaper/技术设计方案.md'
WP = '/workspace/text2charts-whitepaper/产品白皮书.md'

def load(p):
    return open(p, encoding='utf-8').read()

tech = load(TECH)
wp = load(WP)

# 门禁族定义：(前缀, 正则, 文档中"定义处"的锚点特征)
FAMILIES = [
    ('DG', r'\bDG(\d+)\b', '方言'),
    ('FG', r'\bFG(\d+)\b', '联邦'),
    ('UX', r'\bUX(\d+)\b', '连接器'),
    ('P',  r'\bP(\d+)\b(?!\d)', '缓存属性'),
]

DECIDABLE = re.compile(r'\d|必须|禁止|不得|一致|≤|≥|100%|0 命中|全绿|拒绝|相等')

def section_of(text, idx):
    """返回 idx 所在的最近二级标题"""
    head = text.rfind('\n## ', 0, idx)
    if head < 0: head = 0
    end = text.find('\n', head+1)
    return text[head:end].strip('# \n')

report = {'families': {}, 'orphans': [], 'no_criterion': [], 'no_wbs': [], 'summary': {}}

# WBS 段：从 "## 11" 或 WBS 标题到下一章
wbs_start = tech.find('WBS')
wbs_region = tech[wbs_start:] if wbs_start > 0 else ''

for prefix, rx, label in FAMILIES:
    ids = sorted({int(m.group(1)) for m in re.finditer(rx, tech)})
    report['families'][prefix] = {'label': label, 'ids': ids, 'count': len(ids)}
    for n in ids:
        gid = f'{prefix}{n}'
        # 找定义行（表格行且含该编号）
        lines = [ (i, l) for i, l in enumerate(tech.split('\n')) if re.search(rf'\b{gid}\b', l) ]
        # 定义处：表格行，或以 "P3 " 这类行首编号开头的代码块行
        defs = [l for _, l in lines if l.strip().startswith('|') or re.match(rf'^{gid}[\s:]', l.strip())]
        has_criterion = any(DECIDABLE.search(l) for l in defs) if defs else False
        in_wbs = bool(re.search(rf'\b{gid}\b', wbs_region))
        in_wp = bool(re.search(rf'\b{gid}\b', wp))
        rec = {'gate': gid, 'defs': len(defs), 'criterion': has_criterion,
               'wbs': in_wbs, 'whitepaper': in_wp,
               'sections': sorted({section_of(tech, tech.find(l)) for l in defs})[:3]}
        if not defs:
            report['orphans'].append(rec)
        elif not has_criterion:
            report['no_criterion'].append(rec)
        if not in_wbs:
            report['no_wbs'].append(gid)
        # 测试层归属：同一段（±3 行）内是否出现 单元/契约/E2E/基准/人工/benchmark
        idx0 = next((i for i, l in enumerate(tech.split('\n')) if re.search(rf'\b{gid}\b', l) and (l.strip().startswith('|') or re.match(rf'^{gid}[\s:]', l.strip()))), None)
        win = '\n'.join(tech.split('\n')[max(0,(idx0 or 0)-3):(idx0 or 0)+4])
        has_layer = bool(re.search(r'单元|契约|E2E|基准|人工|benchmark|property|快照', win))
        if not has_layer: report.setdefault('no_layer', []).append(gid)

report['summary'] = {
    'total_gates': sum(v['count'] for v in report['families'].values()),
    'orphans': len(report['orphans']),
    'no_criterion': len(report['no_criterion']),
    'no_wbs': len(report['no_wbs']),
    'no_wbs_list': report['no_wbs'],
    'no_layer': len(report.get('no_layer', [])),
    'no_layer_list': report.get('no_layer', []),
}
print(json.dumps(report, ensure_ascii=False, indent=1))
json.dump(report, open('/tmp/poc27_report.json','w'), ensure_ascii=False, indent=1)
