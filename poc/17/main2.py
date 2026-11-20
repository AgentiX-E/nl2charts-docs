#!/usr/bin/env python3
# POC-17 (vectorized): audit McNemar sample-size table by Monte Carlo
import math, json
import numpy as np
from statistics import NormalDist
from scipy.stats import binom

rng = np.random.default_rng(11)
Z = NormalDist()
REPS = 20000

def power(n, p1, delta, disc, alpha=0.05):
    b = (disc - delta) / 2
    c = (disc + delta) / 2
    if b < 0: return None
    bb = rng.binomial(n, b, REPS)
    cc = rng.binomial(n, c, REPS)
    m = bb + cc
    # exact two-sided McNemar via binomial tail, vectorized per unique m
    rej = 0
    for b_i, c_i, m_i in zip(bb, cc, m):
        if m_i == 0: continue
        k = min(b_i, c_i)
        if 2 * binom.cdf(k, m_i, 0.5) < alpha:
            rej += 1
    return rej / REPS, b, c

def connor_n(delta, disc, alpha=0.05, power_=0.8):
    za, zb = Z.inv_cdf(1 - alpha/2), Z.inv_cdf(power_)
    b, c = (disc - delta)/2, (disc + delta)/2
    return math.ceil((za*math.sqrt(b+c) + zb*math.sqrt((b+c)-(c-b)**2))**2 / (c-b)**2)

DOC = {0.10: 320, 0.07: 660, 0.05: 1300, 0.04: 2000, 0.03: 3400, 0.02: 7800}
rows = []
print(f"{'delta':>6} {'disc':>5} {'doc_n':>6} {'power@doc':>9} {'connor_n':>9} {'power@connor':>12}")
for delta, doc_n in DOC.items():
    for disc in (0.20, 0.30, 0.40):
        p_doc, b, c = power(doc_n, 0.70, delta, disc)
        n_c = connor_n(delta, disc)
        p_c, _, _ = power(min(n_c, 12000), 0.70, delta, disc)
        rows.append(dict(delta=delta, disc=disc, doc_n=doc_n, power_at_doc=round(p_doc,3),
                         connor_n=n_c, power_at_connor=round(p_c,3), b=round(b,3), c=round(c,3)))
        print(f"{delta:>6.0%} {disc:>5.0%} {doc_n:>6} {p_doc:>9.2f} {n_c:>9} {p_c:>12.2f}")
json.dump(rows, open('/tmp/poc17_results.json','w'), indent=1)
