#!/usr/bin/env python3
"""POC-37: 基线精度 vs 门槛校准有效性。绝对门槛需要多精确的基线？配对门槛是否更省？"""
import math, json

Z = 1.959964
def wilson(k, n, z=Z):
    p = k / n
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (max(0, c-h), min(1, c+h), h)

def connor_n(delta, disc, za=Z, zb=0.841621):
    if delta <= 0: return None
    num = (za*math.sqrt(disc) + zb*math.sqrt(max(disc - delta**2, 1e-9)))**2
    return math.ceil(num / delta**2)

# ---------- A. 现有基线的精度 ----------
BASE_K, BASE_N = 25, 30          # POC-30 裁定后 25/30
lo, hi, h = wilson(BASE_K, BASE_N)
A = {'point': round(BASE_K/BASE_N*100, 1),
     'ci95': [round(lo*100, 1), round(hi*100, 1)],
     'half_width_pp': round(h*100, 1),
     'gate_88_inside_ci': lo <= 0.88 <= hi,
     'delta_pp': round(0.88 - BASE_K/BASE_N, 3)*100}

# ---------- B. 不同 n 的基线精度 ----------
B = []
for n in (30, 50, 100, 200, 400, 1000, 1300, 2000):
    l, u, hw = wilson(round(0.8333*n), n)
    B.append({'n': n, 'ci95': [round(l*100,1), round(u*100,1)], 'half_width_pp': round(hw*100,1)})

# ---------- C. 要把门禁设在 baseline+Δ，基线需要多少题 ----------
# 判据：基线 CI 半宽 ≤ Δ/2（否则 Δ 淹没在基线自身不确定性里）
C = []
for delta in (0.02, 0.03, 0.047, 0.05, 0.07, 0.10):
    target_h = delta/2
    n_req = math.ceil(Z*Z*0.8333*(1-0.8333) / (target_h**2))
    C.append({'delta_pp': round(delta*100,1), 'max_half_width_pp': round(target_h*100,2),
              'baseline_n_required': n_req})

# ---------- D. 配对设计需要多少题（不需要精确基线） ----------
D = []
for delta in (0.03, 0.047, 0.05, 0.07, 0.10):
    row = {'delta_pp': round(delta*100,1)}
    for disc in (0.20, 0.30, 0.40):
        row[f'n_disc{int(disc*100)}'] = connor_n(delta, disc)
    D.append(row)

# ---------- E. 判定：哪种门禁形态在本项目可行 ----------
E = {
 'absolute_gate_needs_baseline_n': next(c['baseline_n_required'] for c in C if c['delta_pp'] == 4.7),
 'paired_gate_needs_n_40pct': connor_n(0.05, 0.40),
 'paired_gate_needs_n_20pct': connor_n(0.05, 0.20),
 'pilot50_half_width_pp': next(b['half_width_pp'] for b in B if b['n'] == 50),
 'pilot50_can_set_gate_at_delta_pp': None,
}
# 50 题 pilot 能支撑的最小可信 Δ = 2×半宽
E['pilot50_can_set_gate_at_delta_pp'] = round(2*E['pilot50_half_width_pp'], 1)

out = {'A_current_baseline': A, 'B_precision_by_n': B,
       'C_baseline_n_for_delta': C, 'D_paired_n': D, 'E_verdict': E}
json.dump(out, open('/tmp/poc37.json','w'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
