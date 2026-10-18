#!/usr/bin/env python3
"""POC-38: POC-30 两臂的真实配对检验 + eval-plan 生成器（把定门槛变成计算）。"""
import json, math
from math import comb

A = json.load(open('/tmp/poc30_results.json'))
B = json.load(open('/tmp/poc30b_results.json'))
ADJ_A = {'q09','q16','q23','q26','q27','q28'}          # POC-30 已裁定的 R1–R4
ADJ_B = {'q08','q13','q14','q16','q23','q24'}          # 同上口径（B 臂裁定）

okA = {r['id']: r['ok'] for r in A['details']}
okB = {r['id']: r['strict'] for r in B['details']}
adjA = {k: (v or k in ADJ_A) for k, v in okA.items()}
adjB = {k: (v or k in ADJ_B) for k, v in okB.items()}
n = len(okA)

def mcnemar_exact(b, c):
    """双侧精确 McNemar（二项检验，p=0.5）。"""
    m = b + c
    if m == 0: return 1.0
    k = min(b, c)
    tail = sum(comb(m, i) for i in range(0, k+1)) / (2**m)
    return min(1.0, 2*tail)

def tab(x, y):
    b = sum(1 for k in x if (not x[k]) and y[k])   # A 错 B 对
    c = sum(1 for k in x if x[k] and (not y[k]))   # A 对 B 错
    return b, c

ZA, ZB = 1.959964, 0.841621
def connor_n(delta, disc):
    if delta <= 0 or disc <= 0: return None
    num = (ZA*math.sqrt(disc) + ZB*math.sqrt(max(disc - delta**2, 1e-9)))**2
    return math.ceil(num / delta**2)

def min_delta(nq, disc=0.40):
    lo, hi = 0.001, 0.95
    for _ in range(100):
        mid = (lo+hi)/2
        need = connor_n(mid, disc)
        if need is None or need > nq: lo = mid
        else: hi = mid
    return hi

res = {'n': n}
for name, x, y in (('strict', okA, okB), ('adjudicated', adjA, adjB)):
    b, c = tab(x, y)
    m = b + c
    accA = sum(x.values())/n; accB = sum(y.values())/n
    res[name] = {
        'accA': round(accA*100, 1), 'accB': round(accB*100, 1),
        'delta_pp': round((accB-accA)*100, 1),
        'b_Awrong_Bright': b, 'c_Aright_Bwrong': c,
        'discordance': round(m/n, 3),
        'mcnemar_p': round(mcnemar_exact(b, c), 4),
        'significant': mcnemar_exact(b, c) < 0.05,
    }

# 观测到的最大不一致率 → 用于生成器
res['observed_discordance_max'] = max(res['strict']['discordance'], res['adjudicated']['discordance'])
res['min_detectable_delta_at_n30'] = round(min_delta(n, res['observed_discordance_max'])*100, 1)
res['n_required_for_observed_delta'] = {
    'strict': connor_n(res['strict']['delta_pp']/100, res['strict']['discordance']),
    'adjudicated': connor_n(res['adjudicated']['delta_pp']/100, res['adjudicated']['discordance']),
}
# 自洽性：用 POC-17 的已知点校验公式
res['selfcheck_poc17'] = {
    '10pp@40%': connor_n(0.10, 0.40),   # 期望 312
    '5pp@40%': connor_n(0.05, 0.40),    # 期望 1254
    '2pp@40%': connor_n(0.02, 0.40),    # 期望 7847
}

# ---------- 生成器：pilot 结果 → eval-plan 片段 ----------
def make_eval_plan(pilot, target_delta, alpha=0.05, power=0.80):
    disc = pilot['discordance']
    d = target_delta
    nreq = connor_n(d, disc)
    # 绝对形态所需的基线题数（若同时报绝对门槛）
    base_n = math.ceil((ZA**2 * 0.83 * 0.17) / ((d/2)**2))
    # 成本要分开算：题（人工编写/标注）与推理次数（跑模型）
    paired_questions, paired_runs = nreq, 2 * nreq
    absolute_questions, absolute_runs = base_n + nreq, base_n + nreq
    return {
        'design': 'paired',
        'observed_discordance': disc,
        'target_delta_pp': round(d*100, 1),
        'n_required': nreq,
        'cost': {
            'paired': {'questions': paired_questions, 'inference_runs': paired_runs},
            'absolute': {'questions': absolute_questions, 'inference_runs': absolute_runs,
                         'baseline_n': base_n},
            'questions_saved_by_paired': absolute_questions - paired_questions,
            'runs_delta': paired_runs - absolute_runs,
        },
        'yaml': f"""  - id: PRIVATE
    design: paired
    comparison_baseline: "v4.25 / strict {pilot['accA']}% / n={n}"
    metric: ex
    evidence: "off"
    grader: own
    target_delta: {round(d,3)}
    discordance_observed: {disc}     # 来自 pilot {n} 题实测 b+c
    alpha: {alpha}
    power: {power}
    n_required: {nreq}
    gates_ref: [EV1, EV2, EV3, EV4, EV5, EV6]
""",
    }

res['generator_demo'] = {
    'input_pilot': {'n': n, 'discordance': res['observed_discordance_max'],
                    'accA': res['strict']['accA'], 'accB': res['strict']['accB']},
    'for_5pp': make_eval_plan({'discordance': res['observed_discordance_max'],
                               'accA': res['strict']['accA'], 'accB': res['strict']['accB']}, 0.05),
    'for_10pp': make_eval_plan({'discordance': res['observed_discordance_max'],
                                'accA': res['strict']['accA'], 'accB': res['strict']['accB']}, 0.10),
    'for_observed_13_3pp': make_eval_plan({'discordance': res['observed_discordance_max'],
                                           'accA': res['strict']['accA'], 'accB': res['strict']['accB']}, 0.133),
}
json.dump(res, open('/tmp/poc38.json','w'), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
