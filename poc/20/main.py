#!/usr/bin/env python3
# POC-20: is the Studio HCI gate (n=5, -30% task time, UMUX-Lite >=70) statistically powered?
import numpy as np, json
from scipy import stats
rng = np.random.default_rng(5)
REPS = 20000

def power_paired_log(n, effect=0.70, sd_log=0.35, alpha=0.05):
    """Within-subject task time: log ratio ~ N(log(effect), sd_log)."""
    d = rng.normal(np.log(effect), sd_log, size=(REPS, n))
    t = d.mean(axis=1) / (d.std(axis=1, ddof=1) / np.sqrt(n))
    crit = stats.t.ppf(1 - alpha/2, n-1)
    return float((np.abs(t) > crit).mean())

def power_completion(n, p1=0.75, p2=0.90, alpha=0.05):
    """Paired binary (same task, two designs): McNemar exact-ish via normal approx."""
    b = (0.15 + (p2 - p1)) / 2  # both directions
    c = b + (p2 - p1)
    bb = rng.binomial(n, b, REPS); cc = rng.binomial(n, c, REPS)
    m = bb + cc
    with np.errstate(divide='ignore', invalid='ignore'):
        z = np.abs(cc - bb) / np.sqrt(m)
    z = np.where(m == 0, 0, z)
    return float((z > 1.96).mean())

def ci_halfwidth_umux(n, sd=20.0):
    return 1.96 * sd / np.sqrt(n)

print("== task time: detect -30% (paired, sd_log=0.35) ==")
for n in (5, 8, 12, 16, 20, 30, 40):
    print(f"  n={n:>2}: power={power_paired_log(n):.2f}")
print("== detect -15% ==")
for n in (5, 16, 20, 30):
    print(f"  n={n:>2}: power={power_paired_log(n, 0.85):.2f}")
print("== completion 75% -> 90% (paired) ==")
for n in (5, 16, 20, 30):
    print(f"  n={n:>2}: power={power_completion(n):.2f}")
print("== UMUX-Lite 95% CI half-width (sd=20) ==")
for n in (5, 10, 16, 20, 30):
    print(f"  n={n:>2}: ±{ci_halfwidth_umux(n):.1f}")

json.dump({n: power_paired_log(n) for n in (5, 8, 12, 16, 20, 30, 40)}, open('/tmp/poc20_results.json','w'), indent=1)
