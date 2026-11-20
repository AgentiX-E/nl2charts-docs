#!/usr/bin/env python3
"""POC 记录完整性校验（P1-P4），语义签名版"""
import re, json
import os, pathlib
ROOT = pathlib.Path(os.environ.get('NL2CHARTS_DOCS_ROOT') or pathlib.Path(__file__).resolve().parents[2])
T = str(ROOT / '技术设计方案.md')
s = open(T, encoding='utf-8').read()

secs = [(int(m.group(1)), m.group(2), m.start())
        for m in re.finditer(r'^### 14\.\d+ POC-(\d+)：(.+)$', s, re.M)]
def body_of(i):
    return s[secs[i][2]: (secs[i+1][2] if i+1 < len(secs) else len(s))]

# 索引表：从 "**索引（" 到下一个空行后的非表格行
i0 = s.find('**索引（')
i1 = s.find('**自动化校验', i0)
assert i0 > 0 and i1 > i0
seg = s[i0:i1]
_idx_all = [int(x) for x in re.findall(r'^\| (\d+) \|', seg, re.M)]
idx_nums = sorted(set(_idx_all))
# A set comparison hides a duplicated row: the index once carried 68-73 three
# times each while P1 stayed green. Multiplicity is part of the invariant.
idx_dups = sorted({n for n in _idx_all if _idx_all.count(n) > 1})
sec_nums = sorted({n for n, _, _ in secs})

SIG = {
  'q': r'\*\*(假设|问题)\*\*|^假设[:：]|.*吗[？?]\s*$',
  'm': r'\*\*方法\*\*|\*\*设置\*\*|实测|跑\s*\d+|n\s*=\s*\d+|样本|张表|条查询|轮',
  'r': r'\|.*\||\d+(\.\d+)?\s*(ms|µs|s|KB|MB|%)',
  'c': r'\*\*结论\*\*|结论|判断|推论|因此|说明|证实|推翻|不成立|成立',
  'i': r'§\s*\d|ADR-\d|门禁|POC-\d',
}
rows = []
for i, (n, title, _) in enumerate(secs):
    b = body_of(i)
    r = {k: bool(re.search(v, b, re.M)) for k, v in SIG.items()}
    r.update({'poc': n, 'title': title[:24], 'pass': all(r.values())})
    rows.append(r)

out = {
  'sections': len(secs),
  'P1_index_matches_sections': idx_nums == sec_nums and not idx_dups,
  'P1b_index_duplicates': idx_dups,
  'index_only': sorted(set(idx_nums)-set(sec_nums)),
  'sections_only': sorted(set(sec_nums)-set(idx_nums)),
  'P2_pass_rate': f"{sum(1 for r in rows if r['pass'])}/{len(rows)}",
  'P2_fail': [{k: r[k] for k in ('poc','title','q','m','r','c','i')} for r in rows if not r['pass']],
  'P4_assumption_rows': len(re.findall(r'^\| (\d+) \| "', s, re.M)),
}
print(json.dumps(out, ensure_ascii=False, indent=1))
json.dump(out, open('/tmp/poc35_report.json','w'), ensure_ascii=False, indent=1)
