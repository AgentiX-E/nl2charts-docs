#!/usr/bin/env python3
"""POC-61: paired comparison of two schema-card modes on the same 500 questions.

Two runs of the same harness differ only in how the schema card is built. The
right test is not "46.2 vs 52.1" but McNemar on the paired outcomes: for each
question, did exactly one of the two get it right? That isolates the card from
run-to-run noise (which POC-60 measured at ~1pp).

Usage: python3 ablate.py baseline.json candidate.json
"""
from __future__ import annotations

import json
import math
import sys


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    return {r["id"]: r for r in d["rows"]}, d["summary"]


def verdict(r):
    return bool(r.get("status") == "ok" and r.get("ex_set"))


def mcnemar(b: int, c: int):
    """Exact two-sided binomial p-value for b vs c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def main():
    base_rows, base_sum = load(sys.argv[1])
    cand_rows, cand_sum = load(sys.argv[2])
    ids = sorted(set(base_rows) & set(cand_rows))
    b = c = both = neither = 0
    flips_up, flips_down = [], []
    for i in ids:
        x, y = verdict(base_rows[i]), verdict(cand_rows[i])
        if x and y:
            both += 1
        elif y:
            b += 1
            flips_up.append(i)
        elif x:
            c += 1
            flips_down.append(i)
        else:
            neither += 1
    n = len(ids)
    ex_b = sum(1 for i in ids if verdict(base_rows[i])) / n
    ex_c = sum(1 for i in ids if verdict(cand_rows[i])) / n
    p = mcnemar(b, c)
    rep = {
        "n": n,
        "baseline": {"schemaMode": base_sum.get("schemaMode"), "ex": round(ex_b, 4),
                     "cardCharsP50": base_sum.get("cardCharsP50"),
                     "cost_usd": base_sum.get("cost_usd")},
        "candidate": {"schemaMode": cand_sum.get("schemaMode"), "ex": round(ex_c, 4),
                      "cardCharsP50": cand_sum.get("cardCharsP50"),
                      "cost_usd": cand_sum.get("cost_usd")},
        "delta_pp": round((ex_c - ex_b) * 100, 2),
        "paired": {"both_correct": both, "only_candidate": b, "only_baseline": c,
                   "both_wrong": neither, "mcnemar_p": round(p, 6)},
        "flips_up": flips_up, "flips_down": flips_down,
        "significant_at_0.05": p < 0.05,
    }
    print(json.dumps({k: v for k, v in rep.items() if not k.startswith("flips")},
                     ensure_ascii=False, indent=1))
    json.dump(rep, open("ablation.json", "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
