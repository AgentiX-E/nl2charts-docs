#!/usr/bin/env python3
"""POC-65 side-check: what changes if empty results are removed from the denominator?

Observed in an open-source implementation (DeepEye-SQL, MIT, `sql_selection.py`
L119-178): candidates whose execution returns zero rows are kept out of the
consistency score's denominator, and only fall back in when *nothing* returned
rows. The score is then `cluster_size / non_empty_candidates`.

That is a defensible engineering choice for ranking, but it is not the same
quantity as "how many of the N samples agree". When 3 of 5 samples return zero
rows because the filter value is wrong, the remaining 2 agree and the score is
1.0 — the query is certified as maximally confident exactly because it mostly
failed.

This script recomputes both scores from the recorded samples and reports how
many questions the two definitions disagree on, and how many of those are
wrong. No model, no database.

Usage: python3 poc/65/de_score.py poc/65/results.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter

EMPTY = hashlib.sha1(b"[]").hexdigest()[:16]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "results.json"
    doc = json.load(open(path))
    rows = [r for r in doc["rows"] if r.get("status") == "ok" and r.get("samples")]
    n = len(rows)
    disagree, disagree_wrong, with_empty = [], 0, 0
    for r in rows:
        sigs = [s.get("sig") for s in r["samples"] if s.get("sig")]
        if any(s == EMPTY for s in sigs):
            with_empty += 1
        nonempty = [s for s in sigs if s != EMPTY]
        if not nonempty:
            continue
        c = Counter(nonempty)
        score = max(c.values()) / len(nonempty)
        if score >= 0.999 and (r.get("support") or 0) < len(r["samples"]):
            wrong = not r["winner"]["ex_set"]
            disagree.append({"id": r["id"], "support": r.get("support"),
                             "nonEmpty": len(nonempty), "wrong": wrong})
            disagree_wrong += int(wrong)
    wrong_total = sum(1 for r in rows if not r["winner"]["ex_set"])
    print(json.dumps({
        "n": n,
        "questionsWithAnEmptySample": with_empty,
        "scoreDisagreements": len(disagree),
        "disagreementsWrong": disagree_wrong,
        "wrongTotal": wrong_total,
        "disagreementRate": round(len(disagree) / n, 4),
        "examples": disagree[:10],
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
