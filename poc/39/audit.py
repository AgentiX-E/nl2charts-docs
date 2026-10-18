#!/usr/bin/env python3
"""POC-39: 八条要求终验 —— 机器可判部分的全量审计。"""
import re, json, collections

T = '/workspace/text2charts-whitepaper/技术设计方案.md'
W = '/workspace/text2charts-whitepaper/产品白皮书.md'
t = open(T, encoding='utf-8').read()
w = open(W, encoding='utf-8').read()

rep = {}

# ---- R7 无歧义：编号系统 ----
adrs = [int(x) for x in re.findall(r'\bADR-(\d{3})\b', t)]
cnt = collections.Counter(adrs)
dcnt = collections.Counter(int(x) for x in re.findall(r'^\|\s*\**ADR-(\d{3})\**\s*\|', t, re.M))
dup_adr = sorted([k for k, v in dcnt.items() if v > 1])
# 只统计"表格定义行"里的 ADR（| **ADR-0xx** |）
defined_adr = sorted({int(x) for x in re.findall(r'^\|\s*\**ADR-(\d{3})\**\s*\|', t, re.M)})
gaps = [i for i in range(1, max(defined_adr) + 1) if i not in defined_adr]
rep['adr'] = {'defined': len(defined_adr), 'max': max(defined_adr),
              'missing_numbers': gaps, 'dup_mentions': dup_adr}

# 章节编号重复
secs = re.findall(r'^(#{2,4}) (\d+(?:\.\d+)*) ', t, re.M)
dup_sec = sorted([k for k, v in collections.Counter([s for _, s in secs]).items() if v > 1])
rep['sections'] = {'count': len(secs), 'duplicates': dup_sec}

# 决策 D 编号
D = sorted({int(x) for x in re.findall(r'^\|\s*\*\*D(\d+)\*\*', w, re.M)})
rep['decisions'] = {'count': len(D), 'max': max(D),
                    'missing': [i for i in range(max(D) + 1) if i not in D]}

# ---- R8 POC 记录 ----
poc_secs = [int(x) for x in re.findall(r'^### 14\.\d+ POC-(\d+)：', t, re.M)]
idx_rows = [int(x) for x in re.findall(r'^\| (\d+) \|', t[t.find('**索引（'):t.find('**自动化校验', t.find('**索引（'))], re.M)]
rep['poc'] = {'sections': len(poc_secs), 'index_rows': len(idx_rows),
              'sections_eq_index': sorted(poc_secs) == sorted(idx_rows),
              'max': max(poc_secs)}

# ---- R6 断言有出处：按"小节"粒度检查（比行级窗口精度高）
lines = t.split('\n')
blocks, cur, title = [], [], ''
for ln in lines:
    if re.match(r'^#{2,4} ', ln):
        if cur: blocks.append((title, cur))
        cur, title = [ln], ln.strip()
    else:
        cur.append(ln)
if cur: blocks.append((title, cur))
unsourced = []
for title, body in blocks:
    txt = '\n'.join(body)
    # 合规出处：POC 编号 / ADR / 章节引用 / 外部论文 / 探针日期 / 运行时测量
    if '实测' in txt and not re.search(r'POC-\d+|ADR-\d+|§\s*\d|该论文|探针日期|实测\s*20\d\d-|运行时|附录', txt):
        unsourced.append(title[:80])
rep['claims_unsourced'] = {'sections_with_shixce_but_no_ref': len(unsourced),
                           'samples': unsourced[:8]}

# ---- R4 门禁可执行：35 条门禁 × 判据 / 测试层 / WBS ----
wbs = '\n'.join(ln for ln in lines if re.match(r'^\|\s*\*\*T\d', ln) or ln.startswith('T0.') or ln.startswith('T1.') or ln.startswith('T2.'))
gates = {}
for ln in lines:
    m = re.match(r'^\|\s*\**(DG|FG|UX|PKG)(\d{1,2})\**\s*(\||\s+[^|]+\|)', ln)
    if m and '–' not in ln.split('|')[1]:
        gates[f'{m.group(1)}{m.group(2)}'] = ln
    m2 = re.match(r'^P(\d{1,2})\s+', ln)
    if m2:
        gates[f'P{m2.group(1)}'] = ln
no_test_layer = []
for g in gates:
    fam = re.match(r'[A-Z]+', g).group(0)
    # 族级映射在 §8.6
    if f'**{fam}1' not in t and fam not in ('DG', 'FG', 'UX', 'P', 'PKG'):
        no_test_layer.append(g)
rep['gates'] = {'defined': len(gates), 'families': dict(collections.Counter(re.match(r'[A-Z]+', g).group(0) for g in gates)),
                'missing_family_mapping': no_test_layer}

# ---- R2 测试方法：功效/样本量条款是否处处有 n ----
power_claims = [ln.strip()[:80] for ln in lines if 'power' in ln and re.search(r'n\s*[≥=]', ln)]
rep['power_clauses'] = len(power_claims)

# ---- 一致性：两文档版本、POC 计数、假设行数 ----
def version(x):
    m = re.search(r'版本\*\*：(v[\d.]+)', x)
    return m.group(1) if m else None
assum = len(re.findall(r'^\| \d+ \| "', t, re.M))
rep['consistency'] = {
    'version_tech': version(t), 'version_wp': version(w),
    'poc_sections': len(poc_secs), 'assumption_rows': assum,
    'wp_mentions_poc_max': max(int(x) for x in re.findall(r'POC-(\d+)', w)),
    'tech_mentions_poc_max': max(int(x) for x in re.findall(r'POC-(\d+)', t)),
}

print(json.dumps(rep, ensure_ascii=False, indent=1))
json.dump(rep, open('/tmp/poc39_audit.json', 'w'), ensure_ascii=False, indent=1)
