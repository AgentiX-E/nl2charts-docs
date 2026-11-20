#!/usr/bin/env python3
# POC-17: audit the McNemar sample-size table in the whitepaper by Monte Carlo
import math, random, json
from statistics import NormalDist

random.seed(11)
Z = NormalDist()

def mcnemar_power(n, p1, delta, discordance, reps=4000, alpha=0.05):
    """Simulate paired binary outcomes; exact two-sided McNemar (binomial on discordant pairs)."""
    p2 = p1 + delta
    # b = P(sys1 right, sys2 wrong), c = P(sys1 wrong, sys2 right); c-b = delta
    b = (discordance - delta) / 2
    c = (discordance + delta) / 2
    if b < 0:
        return None, b, c
    pa = p1 - b          # both right
    pd = 1 - p1 - c      # both wrong
    rej = 0
    for _ in range(reps):
        bb = sum(1 for _ in range(n) if random.random() < b)
        cc = sum(1 for _ in range(n) if random.random() < c)
        m = bb + cc
        if m == 0:
            continue
        # two-sided exact binomial test with p=0.5
        k = min(bb, cc)
        # P(X<=k) + P(X>=m-k)
        tail = sum(math.comb(m, i) for i in range(0, k + 1)) / 2 ** m
        if 2 * tail < alpha:
            rej += 1
    return rej / reps, b, c

def connor_n(delta, discordance, alpha=0.05, power=0.8):
    za, zb = Z.inv_cdf(1 - alpha / 2), Z.inv_cdf(power)
    b = (discordance - delta) / 2
    c = (discordance + delta) / 2
    num = (za * math.sqrt(b + c) + zb * math.sqrt((b + c) - (c - b) ** 2)) ** 2
    return math.ceil(num / (c - b) ** 2)

DOC = {0.10: 320, 0.07: 660, 0.05: 1300, 0.04: 2000, 0.03: 3400, 0.02: 7800}
rows = []
print(f"{'delta':>6} {'disc':>5} {'doc_n':>6} {'power@doc':>9} {'connor_n':>9} {'power@connor':>12}")
for delta, doc_n in DOC.items():
    for disc in (0.20, 0.30, 0.40):
        p_doc, b, c = mcnemar_power(doc_n, 0.70, delta, disc, reps=2500)
        n_c = connor_n(delta, disc)
        p_c, _, _ = mcnemar_power(n_c, 0.70, delta, disc, reps=2500)
        rows.append({"delta": delta, "discordance": disc, "doc_n": doc_n, "power_at_doc": round(p_doc, 3),
                     "connor_n": n_c, "power_at_connor": round(p_c, 3), "b": round(b, 3), "c": round(c, 3)})
        print(f"{delta:>6.0%} {disc:>5.0%} {doc_n:>6} {p_doc:>9.2f} {n_c:>9} {p_c:>12.2f}")

json.dump(rows, open('/tmp/poc17_results.json', 'w'), indent=1)
