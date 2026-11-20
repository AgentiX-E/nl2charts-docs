#!/usr/bin/env python3
"""POC-36 Part B: eval-plan.yaml 校验器 —— 门禁活性（是否高于基线）+ 样本量可推导性。"""
import json, math

# ---- 文档现状：8 个准确率门禁（来自 §M4/M6 门槛表与 §8.9） ----
PLAN = [
    # id,  benchmark,               target, baseline, baselineSrc, evidence
    ("BIRD-test",     "BIRD test",             0.75, None,   None,               "off"),
    ("SPIDER2-LITE",  "Spider 2.0-Lite",       0.40, None,   None,               "off"),
    ("BIRD-CRITIC",   "BIRD-CRITIC-PG",        0.35, None,   None,               "off"),
    ("BIRD-INTERACT", "BIRD-Interact",         0.15, None,   None,               "n/a"),
    ("DUSQL",         "DuSQL",                 0.70, None,   None,               "off"),
    ("CSPIDER",       "CSpider",               0.80, None,   None,               "off"),
    ("TEXT2VIS",      "Text2Vis",              0.50, None,   None,               "off"),
    ("PRIVATE",       "私有 golden v1.0",      0.80, 0.833,  "POC-30 / n=30",    "off"),
]

Z_A, Z_B = 1.959964, 0.841621  # alpha=0.05 two-sided, power=0.80

def connor_n(delta, discordance, alpha=0.05, power=0.80):
    """配对二分类样本量（Connor 1987）；delta=c-b, discordance=b+c。"""
    if delta <= 0 or discordance <= 0:
        return None
    za, zb = Z_A, Z_B
    num = (za * math.sqrt(discordance) + zb * math.sqrt(max(discordance - delta ** 2, 1e-9))) ** 2
    return math.ceil(num / delta ** 2)

def min_delta(n, discordance=0.40):
    """在给定 n 下，power=0.8 能检出的最小效应（pp）。"""
    lo, hi = 0.001, 0.9
    for _ in range(80):
        mid = (lo + hi) / 2
        need = connor_n(mid, discordance)
        if need is None or need > n:
            lo = mid
        else:
            hi = mid
    return round(hi * 100, 1)

rows, flags = [], {'no_baseline': [], 'vacuous': [], 'unpowered': []}
for gid, bench, target, base, src, ev in PLAN:
    r = {'gate': gid, 'benchmark': bench, 'target': round(target*100, 1), 'evidence': ev,
         'baseline': None if base is None else round(base*100, 1), 'baselineSource': src}
    if base is None:
        r['status'] = 'UNBASELINED'
        r['n'] = None
        flags['no_baseline'].append(gid)
    else:
        delta = target - base
        r['delta_pp'] = round(delta*100, 1)
        if delta <= 0:
            r['status'] = 'VACUOUS'   # 门禁低于/等于基线 → 已达标，无约束力
            r['n'] = None
            flags['vacuous'].append(gid)
        else:
            n = connor_n(delta, 0.40)
            r['status'] = 'OK'
            r['n'] = n
            if n > 2000:
                flags['unpowered'].append({'gate': gid, 'n': n})
    rows.append(r)

# ---- 反向：在文档给定 n 下能检出的最小效应 ----
MIN_DELTA = {str(n): min_delta(n) for n in (320, 660, 1300, 2000, 3400, 7800)}

# ---- 门禁活性判据：target 必须 > baseline + min_delta(n=1300)=? ----
d_crit = min_delta(1300) / 100

out = {
    'gates': rows,
    'coverage': {'total': len(rows),
                 'baselined': sum(1 for r in rows if r['baseline'] is not None),
                 'passing_now': sum(1 for r in rows if r['status'] == 'VACUOUS'),
                 'derivable_n': sum(1 for r in rows if r['n'])},
    'flags': flags,
    'min_detectable_delta_pp_at_n': MIN_DELTA,
    'liveness_rule': {'n': 1300, 'min_delta_pp': round(d_crit*100, 1),
                      'required_target': None},
}
# 私有集修正后的最低目标
base_priv = 0.833
out['liveness_rule']['required_target'] = round((base_priv + d_crit) * 100, 1)

json.dump(out, open('/tmp/poc36_evalplan.json', 'w'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
