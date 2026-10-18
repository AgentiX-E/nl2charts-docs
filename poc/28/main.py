"""
POC-28: 评测标签噪声的量化与校正协议
A. 真实观测：POC-9 的 40 条记录（严格 EX 29/40 vs 裁定后 38/40）
B. Rogan-Gladen 校正 + bootstrap CI（不同裁定样本量）
C. 模拟：随机噪声 vs 分层噪声对准确率与排名的影响
"""
import json, numpy as np
from math import sqrt

rng = np.random.default_rng(20261018)

# ---------- A. 真实观测 ----------
d = json.load(open('/tmp/poc9_results.json'))
b = d['partB']
n = len(b)
strict_ok = sum(1 for x in b if x['ok'])
# 裁定：POC-9 中 11 条"失败"里 10 条仅是投影列不同（每个 variant 5 条）→ 语义正确
ADJUDICATED_OK = 38   # 已由 SQL 原文核实（见 §14.9）
obs = strict_ok / n
print(f"A. 真实观测 n={n} 严格EX={strict_ok}/{n}={obs:.3f} 裁定后={ADJUDICATED_OK}/{n}={ADJUDICATED_OK/n:.3f}")
fn = ADJUDICATED_OK - strict_ok          # 假阴性（真对判错）
print(f"   假阴性 {fn} 条 -> 严格评分的假阴性率(在真对样本中) = {fn/ADJUDICATED_OK:.3f}")

# ---------- B. Rogan-Gladen ----------
# 记号：TPR = P(判对 | 真对)，FPR = P(判对 | 真错)
# 在裁定子集上可直接估计 TPR、FPR；再用全量观测准确率反解真准确率
# theta_obs = theta_true*TPR + (1-theta_true)*FPR
# => theta_true = (theta_obs - FPR) / (TPR - FPR)

def rogan_gladen(obs, tpr, fpr):
    den = tpr - fpr
    if abs(den) < 1e-9:
        return float('nan')
    return (obs - fpr) / den

def simulate_audit(n_audit, obs_acc, tpr, fpr, reps=4000):
    """在裁定子集上估计 TPR/FPR，再校正；返回校正值与 CI"""
    est = []
    for _ in range(reps):
        # 裁定子集里真对的比例未知，按观测反推后抽样（用当前估计做 plug-in）
        true_acc = rogan_gladen(obs_acc, tpr, fpr)
        true_acc = min(max(true_acc, 0.0), 1.0)
        n_true = rng.binomial(n_audit, true_acc)
        n_false = n_audit - n_true
        tpr_h = rng.binomial(n_true, tpr) / max(n_true, 1)
        fpr_h = rng.binomial(n_false, fpr) / max(n_false, 1)
        est.append(rogan_gladen(obs_acc, tpr_h, fpr_h))
    est = np.array([e for e in est if np.isfinite(e)])
    return np.percentile(est, [2.5, 50, 97.5]), np.mean(np.abs(est - np.median(est)) > 1)

print("\nB. Rogan-Gladen 校正（真实观测：TPR=0.947, FPR≈0 作为下界估计）")
TPR_REAL = ADJUDICATED_OK / ADJUDICATED_OK   # 1.0 —— 裁定后都为"真对"，无法从该数据估 TPR
# 用 POC-9 的严格评分行为估：真对中 5/19 被判错 -> TPR=0.737；真错中 0 被判对 -> FPR=0
TPR_REAL, FPR_REAL = 14/19, 0.0
print(f"   由 POC-9 估计 TPR={TPR_REAL:.3f}（真对中 14/19 被严格判对） FPR={FPR_REAL:.3f}")
corr = rogan_gladen(obs, TPR_REAL, FPR_REAL)
print(f"   校正后真准确率 ≈ {corr:.3f}（观测 {obs:.3f}）")
for n_audit in (20, 40, 100, 200, 400, 800):
    (lo, med, hi), p_bad = simulate_audit(n_audit, obs, TPR_REAL, FPR_REAL, reps=3000)
    print(f"   裁定子集 n={n_audit:4d}: 校正={med:.3f} 95%CI=[{lo:.3f},{hi:.3f}] 宽度={hi-lo:.3f} 越界率={p_bad:.3f}")

# ---------- C. 模拟：噪声对准确率与排名 ----------
print("\nC. 模拟：标签噪声（e=0.528）如何扭曲观测与排名")
def observe(true_acc, e_random, n_items, reps=2000, stratified=None):
    """stratified: (share_hard, e_hard) —— 噪声集中在难例上"""
    out = []
    for _ in range(reps):
        if stratified is None:
            correct_true = rng.random(n_items) < true_acc
            labeled_correct = np.where(correct_true, rng.random(n_items) > e_random, rng.random(n_items) < e_random)
        else:
            share_hard, e_hard = stratified
            hard = rng.random(n_items) < share_hard
            c = rng.random(n_items) < true_acc
            # 难例上真对率更低 + 噪声更高
            flip = np.where(hard, rng.random(n_items) < e_hard, rng.random(n_items) < 0.02)
            labeled_correct = np.where(c, ~flip, flip)
        out.append(labeled_correct.mean())
    return np.array(out)

for acc in (0.60, 0.80, 0.90):
    o = observe(acc, 0.528, 500)
    print(f"   真准确率 {acc:.2f} -> 观测（随机噪声 52.8%） {o.mean():.3f} ± {o.std():.3f}")

# 两系统真差 2pp，噪声下能否分辨
a = observe(0.80, 0.528, 500).mean()
b2 = observe(0.82, 0.528, 500).mean()
print(f"   真 80% vs 82% 在噪声下观测：{a:.3f} vs {b2:.3f} -> 差 {b2-a:+.3f}（符号可能翻转）")
flips = 0
for _ in range(500):
    x = observe(0.80, 0.528, 500, reps=1)[0]
    y = observe(0.82, 0.528, 500, reps=1)[0]
    if y < x: flips += 1
print(f"   500 次抽样中「更强的系统被排到后面」的概率 = {flips/500:.3f}")

# 分层噪声：校正假设被破坏
print("\n   分层噪声（80% 题无噪声、20% 题噪声 90%）下的校正偏差：")
strat = (0.20, 0.90)
for acc in (0.80, 0.90):
    o = observe(acc, 0.0, 1000, stratified=strat)
    obs_mean = o.mean()
    # 用"池化"的 TPR/FPR 做校正（错误做法）
    pooled_tpr, pooled_fpr = 1 - (0.2*0.9), 0.2*0.9*0  # 近似：难点上真对被判错 90%
    naive = rogan_gladen(obs_mean, 1-0.2*0.9, 0.0)
    print(f"     真 {acc:.2f} -> 观测 {obs_mean:.3f} -> 池化校正 {naive:.3f}（偏差 {naive-acc:+.3f}）")

# ---------- D. 结论数字 ----------
print("\nD. 关键判据")
n_needed = {}
for target_halfwidth in (0.10, 0.05, 0.03):
    for n_audit in (40, 100, 200, 400, 800, 1600):
        (lo, med, hi), _ = simulate_audit(n_audit, obs, TPR_REAL, FPR_REAL, reps=1500)
        if (hi-lo)/2 <= target_halfwidth:
            n_needed[target_halfwidth] = n_audit
            break
print("   达到目标 CI 半宽所需裁定题数：", n_needed)
