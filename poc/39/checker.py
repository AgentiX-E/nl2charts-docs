#!/usr/bin/env python3
"""POC-39 Part B: eval-plan 检查器 E1-E7 的可执行实现 + 逐规则变异自测。"""
import math, copy, json

ZA, ZB = 1.959964, 0.841621

def min_delta(n, disc=0.40):
    lo, hi = 0.001, 0.95
    for _ in range(100):
        mid = (lo + hi) / 2
        num = (ZA*math.sqrt(disc) + ZB*math.sqrt(max(disc-mid*mid, 1e-9)))**2
        need = math.ceil(num / mid**2)
        if need > n: lo = mid
        else: hi = mid
    return hi

def connor_n(delta, disc):
    num = (ZA*math.sqrt(disc) + ZB*math.sqrt(max(disc-delta**2, 1e-9)))**2
    return math.ceil(num/delta**2)

REGISTRY = {f'EV{i}' for i in range(1, 7)} | {f'DG{i}' for i in range(1, 12)} | \
           {f'FG{i}' for i in range(1, 9)} | {f'UX{i}' for i in range(1, 7)} | \
           {f'P{i}' for i in range(1, 11)} | {'G1', 'G2', 'G3', 'G4'}

CLEAN = {
  'version': 1, 'alpha': 0.05, 'power': 0.80, 'primary_metric': 'ex',
  'gates': [
    {'id': 'PRIVATE', 'design': 'paired', 'benchmark': 'private-golden-v1',
     'metric': 'ex', 'evidence': 'off', 'grader': 'own',
     'target_delta': 0.05, 'discordance_observed': 0.40, 'n_required': 1254,
     'comparison_baseline': 'v4.25/63.3%/n=30',
     'adjudication': {'sample': 200, 'kappa_min': 0.70},
     'gates_ref': ['EV1', 'EV2', 'EV3', 'EV4', 'EV5', 'EV6']},
    {'id': 'SPIDER2LITE', 'design': 'anchored', 'benchmark': 'spider2-lite',
     'metric': 'ex', 'evidence': 'off', 'grader': 'own', 'target': 0.55,
     'anchor': 'mnemiq 59.8% (own grader)', 'n_required': 547,
     'adjudication': {'sample': 200, 'kappa_min': 0.70},
     'gates_ref': ['EV1', 'EV4', 'EV6']},
  ],
}

def check(plan):
    errs = []
    A, P = plan.get('alpha', 0.05), plan.get('power', 0.80)
    if plan.get('primary_metric') != 'ex':
        errs.append(('E4', 'primary_metric 必须是 ex'))
    for g in plan['gates']:
        gid = g.get('id', '?')
        # E1 基线可追溯（绝对/配对都必须说清"与谁比"）
        if g['design'] in ('absolute', 'paired'):
            if not g.get('baseline') and not g.get('comparison_baseline'):
                errs.append(('E1', f'{gid} 缺 baseline/comparison_baseline'))
        # E2 门禁活性
        if g['design'] == 'absolute':
            if g.get('target') is None or g.get('baseline') is None:
                errs.append(('E2', f'{gid} absolute 缺 target/baseline'))
            else:
                n = g.get('n_required') or 0
                md = min_delta(n) if n else 1.0
                if g['target'] - g['baseline'] < md:
                    errs.append(('E2', f'{gid} VACUOUS: Δ{g["target"]-g["baseline"]:.3f} < 最小可检出 {md:.3f}'))
        if g['design'] == 'paired':
            if not g.get('target_delta'):
                errs.append(('E2', f'{gid} paired 缺 target_delta'))
            elif g.get('comparison_baseline') is None:
                errs.append(('E2', f'{gid} paired 缺对照'))
        # E3 n 自洽（±5%）
        if g['design'] == 'paired' and g.get('target_delta') and g.get('discordance_observed'):
            need = connor_n(g['target_delta'], g['discordance_observed'])
            got = g.get('n_required') or 0
            if need and got and abs(got - need) / need > 0.05:
                errs.append(('E3', f'{gid} n_required {got} 与公式 {need} 差 >5%'))
        # E4 evidence 必填
        if g.get('evidence') not in ('on', 'off'):
            errs.append(('E4', f'{gid} 缺 evidence'))
        # E5 gates_ref 有效
        for r in g.get('gates_ref', []):
            if r not in REGISTRY:
                errs.append(('E5', f'{gid} 引用未注册 {r}'))
        if not g.get('gates_ref'):
            errs.append(('E5', f'{gid} 无 gates_ref'))
        # E6 裁定规模
        adj = g.get('adjudication') or {}
        if adj.get('sample', 0) < 200 or adj.get('kappa_min', 0) < 0.7:
            errs.append(('E6', f'{gid} adjudication 不足'))
        # E7 grader / 基线精度
        if g['design'] == 'anchored' and g.get('grader') not in ('official', 'own'):
            errs.append(('E7', f'{gid} anchored 缺 grader'))
        if g['design'] == 'absolute':
            d = g.get('target_delta') or ((g.get('target') or 0) - (g.get('baseline') or 0))
            if d > 0:
                b = g.get('baseline', 0.5)
                need_base = math.ceil(ZA**2 * b * (1-b) / ((d/2)**2))
                if (g.get('baseline_n') or 0) < need_base:
                    errs.append(('E7', f'{gid} baseline_n 不足 {need_base}'))
    return errs

def mutate(plan, kind):
    p = copy.deepcopy(plan)
    g = p['gates'][0]
    if kind == 'E1_drop_baseline':
        g.pop('comparison_baseline', None); g.pop('baseline', None)
    elif kind == 'E2_vacuous':
        p['gates'].append({'id': 'ABS', 'design': 'absolute', 'benchmark': 'x', 'metric': 'ex',
                           'evidence': 'off', 'target': 0.833, 'baseline': 0.833,
                           'n_required': 1300, 'baseline_n': 2000,
                           'adjudication': {'sample': 200, 'kappa_min': 0.7},
                           'gates_ref': ['EV1']})
    elif kind == 'E3_n_mismatch':
        g['n_required'] = 300           # 公式给 1254
    elif kind == 'E4_evidence_missing':
        g.pop('evidence', None)
    elif kind == 'E5_bad_ref':
        g['gates_ref'] = ['EV1', 'DG99']
    elif kind == 'E6_small_adjudication':
        g['adjudication'] = {'sample': 50, 'kappa_min': 0.6}
    elif kind == 'E7_no_grader':
        p['gates'][1].pop('grader', None)
    return p

out = {'clean': [], 'mutation': {}}
out['clean'] = check(CLEAN)
for kind in ('E1_drop_baseline', 'E2_vacuous', 'E3_n_mismatch', 'E4_evidence_missing',
             'E5_bad_ref', 'E6_small_adjudication', 'E7_no_grader'):
    errs = check(mutate(CLEAN, kind))
    rules = sorted({e[0] for e in errs})
    out['mutation'][kind] = {'caught': bool(errs), 'by': rules, 'sample': errs[:2]}
out['summary'] = {
  'clean_passes': len(out['clean']) == 0,
  'mutations_caught': sum(1 for v in out['mutation'].values() if v['caught']),
  'mutations_total': len(out['mutation']),
  'each_caught_by_own_rule': all(k.split('_')[0] in v['by'] for k, v in out['mutation'].items()),
}
json.dump(out, open('/tmp/poc39_checker.json', 'w'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
