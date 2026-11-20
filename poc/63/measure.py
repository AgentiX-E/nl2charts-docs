#!/usr/bin/env python3
"""POC-63 (offline half): how often does lexical linking drop a table the gold needs?

This is the cheapest honest measurement in the whole repo: no model, no tokens,
runs in seconds. If recall@4 is not ~1.0, the end-to-end run cannot attribute a
loss to the generator — the table was never in the prompt.

Reports recall@k, full coverage rate, and how much of the schema survived, split
by difficulty so a regression on "challenging" is visible instead of averaged away.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import link  # noqa: E402
import run as harness  # noqa: E402  (reuse db lookup; no model calls happen here)

KS = [1, 2, 3, 4, 6]
_STATS: dict[str, dict] = {}


def stats_for(db_path):
    if db_path not in _STATS:
        _STATS[db_path] = link.table_stats(db_path)
    return _STATS[db_path]


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/data/bird_mini_dev")
    qfile = os.path.join(data_dir, "data", "mini_dev_sqlite-00000-of-00001.json")
    if not os.path.exists(qfile):
        for root, _d, files in os.walk(data_dir):
            for f in files:
                if f.endswith(".json") and "mini_dev" in f:
                    qfile = os.path.join(root, f)
                    break
    qs = json.load(open(qfile, encoding="utf-8"))
    db_dir = os.path.join(data_dir, "databases")

    per_k = {k: {"gold": 0, "hit": 0, "full": 0} for k in KS}
    by_diff = {}
    by_size = {"small(<=6)": {"n": 0, "gold": 0, "hit4": 0}, "large(>6)": {"n": 0, "gold": 0, "hit4": 0}}
    missed = []
    reduction = {"fullCols": 0, "linkedCols": 0, "fullTables": 0, "linkedTables": 0}
    skipped = 0

    for q in qs:
        db_path = harness.find_db(db_dir, q["db_id"])
        if not db_path:
            skipped += 1
            continue
        st = stats_for(db_path)
        known = list(st)
        gold = link.gold_tables(q["SQL"], known)
        if not gold:
            skipped += 1
            continue
        d = (q.get("difficulty") or "unknown").lower()
        b = by_diff.setdefault(d, {"n": 0, "covered4": 0})
        b["n"] += 1
        for k in KS:
            picked, _ = link.select(st, q["question"], k=k, with_fk=True)
            inter = len(set(gold) & set(picked))
            per_k[k]["gold"] += len(gold)
            per_k[k]["hit"] += inter
            if set(gold) <= set(picked):
                per_k[k]["full"] += 1
                if k == 4:
                    b["covered4"] += 1
        bucket = "small(<=6)" if len(st) <= 6 else "large(>6)"
        by_size[bucket]["n"] += 1
        picked4, _ = link.select(st, q["question"], k=4, with_fk=True)
        by_size[bucket]["gold"] += len(gold)
        by_size[bucket]["hit4"] += len(set(gold) & set(picked4))
        reduction["fullTables"] += len(st)
        reduction["linkedTables"] += len(picked4)
        reduction["fullCols"] += sum(len(v["cols"]) for v in st.values())
        reduction["linkedCols"] += sum(len(st[t]["cols"]) for t in picked4)
        if not set(gold) <= set(picked4):
            missed.append({"id": q["question_id"], "db": q["db_id"], "gold": gold,
                           "picked": picked4, "difficulty": d})

    n = len(qs) - skipped
    table = {str(k): {"recall": round(per_k[k]["hit"] / per_k[k]["gold"], 4),
                      "coverage": round(per_k[k]["full"] / n, 4)} for k in KS}
    for d, b in by_diff.items():
        b["coverage4"] = round(b["covered4"] / b["n"], 4)
    for s2, b in by_size.items():
        b["recall4"] = round(b["hit4"] / b["gold"], 4) if b["gold"] else None
    rep = {
        "questions": len(qs), "measured": n, "skipped": skipped,
        "recallAtK": table,
        "byDifficulty": by_diff,
        "schemaReduction": {
            "tables": round(reduction["linkedTables"] / reduction["fullTables"], 3),
            "columns": round(reduction["linkedCols"] / reduction["fullCols"], 3),
        },
        "missedAt4": missed[:40],
        "missedAt4Count": len(missed),
        "bySchemaSize": by_size,
        "gate": {"recallAt4": round(per_k[4]["hit"] / per_k[4]["gold"], 4),
                 "coverageAt4": round(per_k[4]["full"] / n, 4),
                 "threshold": 0.9,
                 "pass": round(per_k[4]["hit"] / per_k[4]["gold"], 4) >= 0.9},
    }
    json.dump(rep, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: rep[k] for k in ("questions", "measured", "skipped", "recallAtK",
                                          "bySchemaSize", "schemaReduction", "missedAt4Count", "gate")},
                     ensure_ascii=False, indent=1))
    # This step MEASURES. The pass/fail decision lives in the summary, after the
    # end-to-end run, so a weak retriever still produces both numbers instead of
    # only the one that failed.
    return 0


if __name__ == "__main__":
    sys.exit(main())
