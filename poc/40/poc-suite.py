#!/usr/bin/env python3
"""poc-suite: 把 POC-17 / 36 / 37 / 38 / 39 的算式收成一个可复算的冻结夹具。

用法：
  python3 poc-suite.py --check   # 逐项断言文档中的数字，全部吻合则 exit 0
  python3 poc-suite.py --demo    # 打印 eval-plan 片段（配对形态）
  python3 poc-suite.py --power 5 # 给定 Δ(pp)，打印所需 n（不一致率 40%）

设计约束：
  * 零第三方依赖，单文件，可粘贴进任何环境；
  * 不含产品逻辑（不读写 DB、不调 LLM），只做统计与规则校验；
  * 所有断言对应文档中的具体数字，任一不吻合即失败。
"""
import argparse, math, sys

ZA, ZB = 1.959964, 0.841621  # α=0.05 双侧，power=0.80

# ---------- 统计核心 ----------
def connor_n(delta_pp, discordance):
    """配对二分类样本量（Connor）。delta 单位 pp。"""
    d = delta_pp / 100
    if d <= 0 or discordance <= 0:
        return None
    num = (ZA * math.sqrt(discordance) + ZB * math.sqrt(max(discordance - d * d, 1e-9))) ** 2
    return math.ceil(num / (d * d))

def min_delta_pp(n, discordance=0.40):
    """给定 n，反算 power=0.8 能检出的最小效应（pp）。"""
    lo, hi = 0.01, 95.0
    for _ in range(200):
        mid = (lo + hi) / 2
        need = connor_n(mid, discordance)
        if need is None or need > n:
            lo = mid
        else:
            hi = mid
    return hi

def wilson(k, n, z=ZA):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h), h

def mcnemar_exact(b, c):
    """双侧精确 McNemar（二项检验）。"""
    m = b + c
    if m == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(m, i) for i in range(0, k + 1)) / (2 ** m)
    return min(1.0, 2 * tail)

def baseline_n_required(delta_pp, p=0.8333):
    """绝对门禁：基线 CI 半宽 ≤ Δ/2 时所需基线题数。"""
    return math.ceil(ZA * ZA * p * (1 - p) / ((delta_pp / 200) ** 2))

# ---------- E1–E7 检查器 ----------
REGISTRY = ({f'EV{i}' for i in range(1, 7)} | {f'DG{i}' for i in range(1, 12)} |
            {f'FG{i}' for i in range(1, 9)} | {f'UX{i}' for i in range(1, 7)} |
            {f'P{i}' for i in range(1, 11)} | {'G1', 'G2', 'G3', 'G4'})

def check_plan(plan):
    errs = []
    if plan.get('primary_metric') != 'ex':
        errs.append(('E4', 'primary_metric 必须是 ex'))
    for g in plan['gates']:
        gid = g.get('id', '?')
        if g['design'] in ('absolute', 'paired') and not (g.get('baseline') or g.get('comparison_baseline')):
            errs.append(('E1', f'{gid} 缺 baseline/comparison_baseline'))
        if g['design'] == 'absolute':
            if g.get('target') is None or g.get('baseline') is None:
                errs.append(('E2', f'{gid} absolute 缺 target/baseline'))
            else:
                md = min_delta_pp(g.get('n_required') or 1) / 100
                if g['target'] - g['baseline'] < md:
                    errs.append(('E2', f'{gid} VACUOUS'))
            d = g.get('target_delta') or ((g.get('target') or 0) - (g.get('baseline') or 0))
            if d > 0:
                need = baseline_n_required(d * 100, g.get('baseline', 0.5))
                if (g.get('baseline_n') or 0) < need:
                    errs.append(('E7', f'{gid} baseline_n 不足 {need}'))
        if g['design'] == 'paired':
            if not g.get('target_delta'):
                errs.append(('E2', f'{gid} paired 缺 target_delta'))
            elif g.get('comparison_baseline') is None:
                errs.append(('E2', f'{gid} paired 缺对照'))
            if g.get('target_delta') and g.get('discordance_observed'):
                need = connor_n(g['target_delta'] * 100, g['discordance_observed'])
                got = g.get('n_required') or 0
                if need and got and abs(got - need) / need > 0.05:
                    errs.append(('E3', f'{gid} n_required {got} ≠ {need}'))
        if g.get('evidence') not in ('on', 'off'):
            errs.append(('E4', f'{gid} 缺 evidence'))
        refs = g.get('gates_ref') or []
        if not refs:
            errs.append(('E5', f'{gid} 无 gates_ref'))
        for r in refs:
            if r not in REGISTRY:
                errs.append(('E5', f'{gid} 引用未注册 {r}'))
        adj = g.get('adjudication') or {}
        if adj.get('sample', 0) < 200 or adj.get('kappa_min', 0) < 0.7:
            errs.append(('E6', f'{gid} adjudication 不足'))
        if g['design'] == 'anchored' and g.get('grader') not in ('official', 'own'):
            errs.append(('E7', f'{gid} anchored 缺 grader'))
    return errs

# ---------- 自检：逐项对齐文档数字 ----------
CHECKS = [
    # (标签, 实算, 文档值, 容差)
    ('POC-17  10pp@40% n',        connor_n(10, 0.40),          312,  0),
    ('POC-17   5pp@40% n',        connor_n(5, 0.40),          1254,  0),
    ('POC-17   3pp@40% n',        connor_n(3, 0.40),          3487,  0),
    ('POC-17   2pp@40% n',        connor_n(2, 0.40),          7847,  0),
    ('POC-36  n=320 → Δ',         min_delta_pp(320),           9.9, 0.1),
    ('POC-36  n=1300 → Δ',        min_delta_pp(1300),          4.9, 0.1),
    ('POC-36  n=3400 → Δ',        min_delta_pp(3400),          3.0, 0.1),
    ('POC-36  n=7800 → Δ',        min_delta_pp(7800),          2.0, 0.1),
    ('POC-37  wilson(25,30) 下限', wilson(25, 30)[0] * 100,   66.4, 0.1),
    ('POC-37  wilson(25,30) 上限', wilson(25, 30)[1] * 100,   92.7, 0.1),
    ('POC-37  半宽 pp',            wilson(25, 30)[2] * 100,   13.1, 0.1),
    ('POC-37  Δ4.7 基线 n',        baseline_n_required(4.7),   967,  0),
    ('POC-38  McNemar b=8,c=4',    mcnemar_exact(8, 4),      0.388, 0.001),
    ('POC-38  McNemar b=4,c=0',    mcnemar_exact(4, 0),      0.125, 0.001),
    ('POC-38  13.3pp@40% n',       connor_n(13.3, 0.40),       176,  0),
    ('POC-38  n=30 → 最小 Δ',      min_delta_pp(30),          31.1, 0.2),
]

def run_check():
    bad = []
    for name, got, want, tol in CHECKS:
        ok = abs(got - want) <= tol if tol else round(got) == want
        print(f"{'PASS' if ok else 'FAIL'}  {name:<28} got={got:.4g} want={want}")
        if not ok:
            bad.append(name)
    return bad

DEMO_PLAN = {
    'version': 1, 'alpha': 0.05, 'power': 0.80, 'primary_metric': 'ex',
    'gates': [{
        'id': 'PRIVATE', 'design': 'paired', 'benchmark': 'private-golden-v1',
        'metric': 'ex', 'evidence': 'off', 'grader': 'own',
        'target_delta': 0.05, 'discordance_observed': 0.40,
        'n_required': connor_n(5, 0.40),
        'comparison_baseline': 'v4.25/63.3%/n=30',
        'adjudication': {'sample': 200, 'kappa_min': 0.70},
        'gates_ref': ['EV1', 'EV2', 'EV3', 'EV4', 'EV5', 'EV6'],
    }],
}

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--demo', action='store_true')
    ap.add_argument('--power', type=float, help='目标 Δ(pp)，输出所需 n')
    a = ap.parse_args()

    if a.power is not None:
        print(f'Δ={a.power}pp @40% → n={connor_n(a.power, 0.40)}；@20% → n={connor_n(a.power, 0.20)}')
    if a.demo:
        for g in DEMO_PLAN['gates']:
            print(f"  - id: {g['id']}\n    design: {g['design']}\n"
                  f"    target_delta: {g['target_delta']}\n"
                  f"    discordance_observed: {g['discordance_observed']}\n"
                  f"    n_required: {g['n_required']}")
        print('checker errors:', check_plan(DEMO_PLAN))
    if a.check:
        bad = run_check()
        print(f'\n{len(CHECKS) - len(bad)}/{len(CHECKS)} PASS')
        sys.exit(1 if bad else 0)
