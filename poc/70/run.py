#!/usr/bin/env python3
"""POC-70: when candidates disagree, can a judge pick better than the majority?

POC-65 showed the two regimes are not the same problem:

  support = N   one candidate, 52.7% correct  -> selection cannot help
  support < N   several candidates, 12.3%     -> selection is the only lever

Majority voting already runs there and picks the most frequent *result*. A
judge sees the question, the SQL and a preview of each result, and picks one.
This experiment asks whether that is better than counting — on exactly the 65
questions where a choice exists, so the comparison is paired and the cost is
proportional to the disagreement rate (not to all 500).

  arm M  majority by result signature  (already recorded in POC-65)
  arm J  one call: "which candidate is most likely correct? reply with index"

Gold is used only for scoring, after the judge has committed.

Usage:
  python3 poc/70/run.py --selftest
  python3 poc/70/run.py --data-dir ~/data/bird_mini_dev
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import ex  # noqa: E402
import run as H  # noqa: E402

JUDGE_SYS = (
    "You are a SQL reviewer. You are given a question, a database schema and "
    "several candidate queries with a preview of their results. Pick the single "
    "candidate most likely to answer the question correctly. "
    "Reply with the candidate number only."
)


def candidates(row, limit=4):
    """Distinct SQL strings among the samples, winner first, deduplicated."""
    seen, out = set(), []
    order = sorted(row.get("samples") or [], key=lambda s: 0 if s.get("sig") == (row.get("winner") or {}).get("sig") else 1)
    for s in order:
        sql = (s.get("sql") or "").strip()
        if not sql:
            continue
        key = ex.normalize_sql(sql)
        if key in seen:
            continue
        seen.add(key)
        out.append({"sql": sql, "sig": s.get("sig"), "ex_set": s.get("ex_set")})
        if len(out) == limit:
            break
    return out


def preview(db_path, sql, k=4):
    r = ex.execute(db_path, sql)
    if not r.ok:
        return "(error: %s)" % (r.error or "")[:80]
    if not r.rows:
        return "(0 rows)"
    head = r.rows[:k]
    return "\n".join(" | ".join("NULL" if c is None else str(c)[:40] for c in row) for row in head)


def judge_prompt(question, card, cands, previews):
    lines = [card, "", "Question: %s" % question, ""]
    for i, c in enumerate(cands):
        lines.append("Candidate %d:\n%s\nResult preview:\n%s\n" % (i, c["sql"], previews[i]))
    lines.append("Which candidate is most likely correct? Reply with the number only.")
    return [{"role": "system", "content": JUDGE_SYS},
            {"role": "user", "content": "\n".join(lines)}]


def parse_index(text, n):
    m = re.search(r"\b(\d+)\b", text or "")
    if not m:
        return None
    i = int(m.group(1))
    return i if 0 <= i < n else None


def one(item, db_dir, data_dir):
    row, gold_sql = item
    out = {"id": row["id"], "db_id": row["db_id"]}
    db_path = H.find_db(db_dir, row["db_id"])
    if not db_path:
        out["status"] = "db_missing"
        return out
    g = ex.execute(db_path, gold_sql)
    if not g.ok:
        out["status"] = "gold_error"
        return out
    gold = g.rows
    cands = candidates(row)
    if len(cands) < 2:
        out["status"] = "single"
        return out
    card = H.schema_card(db_path, row["db_id"], "samples", data_dir, row["question"])
    previews = [preview(db_path, c["sql"]) for c in cands]
    try:
        r = H.call(judge_prompt(row["question"], card, cands, previews), max_tokens=8)
    except RuntimeError as e:
        out.update(status="judge_failed", error=str(e))
        return out
    pick = parse_index(r["text"], len(cands))
    out["picked"] = pick
    out["raw"] = (r["text"] or "")[:40]
    out["usage"] = r["usage"]
    out["nCandidates"] = len(cands)
    out["majorityCorrect"] = bool(row.get("winner", {}).get("ex_set"))
    if pick is None:
        out["judgeCorrect"] = None
        out["status"] = "unparsed"
        return out
    sql = cands[pick]["sql"]
    res = ex.execute(db_path, sql) if ex.guard(sql)[0] else None
    out["judgeCorrect"] = bool(res and res.ok and ex.compare(res.rows, gold)[1])
    out["status"] = "ok"
    return out


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def summarise(rows, n_total):
    ok = [r for r in rows if r["status"] == "ok"]
    j = sum(1 for r in ok if r["judgeCorrect"])
    m = sum(1 for r in ok if r["majorityCorrect"])
    only_j = sum(1 for r in ok if r["judgeCorrect"] and not r["majorityCorrect"])
    only_m = sum(1 for r in ok if r["majorityCorrect"] and not r["judgeCorrect"])
    u = {"in": 0, "out": 0, "hit": 0, "miss": 0}
    for r in ok:
        for k in u:
            u[k] += (r.get("usage") or {}).get(k, 0) or 0
    cost = (u["miss"] * H.PRICE["in_miss"] + u["hit"] * H.PRICE["in_hit"]
            + u["out"] * H.PRICE["out"]) / 1e6
    return {
        "n": n_total, "disagreed": len(rows), "scored": len(ok),
        "majority": {"correct": m, "accuracy": round(m / len(ok), 4) if ok else None},
        "judge": {"correct": j, "accuracy": round(j / len(ok), 4) if ok else None},
        "mcnemar": {"onlyJudge": only_j, "onlyMajority": only_m,
                    "p": round(mcnemar_exact(only_j, only_m), 6)},
        "netPpOver500": round(100 * (j - m) / n_total, 2),
        "cost_usd": round(cost, 4),
        "avgCandidates": round(sum(r["nCandidates"] for r in ok) / len(ok), 2) if ok else None,
    }


def selftest():
    cases = []
    for text, n, want in (("2", 4, 2), ("Candidate 1", 3, 1), ("I pick 9", 3, None),
                          ("no number", 2, None), ("0", 1, 0)):
        got = parse_index(text, n)
        cases.append({"case": "index %r/%d" % (text, n), "got": got, "pass": got == want})
    row = {"winner": {"sig": "a"}, "samples": [
        {"sql": "SELECT 1", "sig": "a", "ex_set": True},
        {"sql": "SELECT 1 ", "sig": "a", "ex_set": True},
        {"sql": "SELECT 2", "sig": "b", "ex_set": False},
        {"sql": "", "sig": None},
    ]}
    c = candidates(row)
    cases.append({"case": "dedup keeps winner first", "got": [x["sql"] for x in c],
                  "pass": len(c) == 2 and c[0]["sql"].strip() == "SELECT 1"})
    for b, cc, want in ((3, 0, 0.25), (9, 2, 0.065429), (0, 0, 1.0)):
        got = mcnemar_exact(b, cc)
        cases.append({"case": "mcnemar %d/%d" % (b, cc), "got": round(got, 6),
                      "pass": abs(got - want) < 1e-6})
    ok = all(x["pass"] for x in cases)
    return {"cases": cases, "pass": sum(1 for x in cases if x["pass"]),
            "total": len(cases), "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--results", default=os.path.join(HERE, "..", "65", "results.json"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=os.path.join(HERE, "results.json"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        r = selftest()
        print(json.dumps({k: v for k, v in r.items() if k != "cases"}, ensure_ascii=False))
        for c in r["cases"]:
            if not c["pass"]:
                print("FAIL", c)
        raise SystemExit(0 if r["ok"] else 1)
    if not args.data_dir:
        raise SystemExit("--data-dir is required")

    prev = json.load(open(args.results))
    n_total = prev["summary"]["n"]
    targets = [r for r in prev["rows"]
               if r.get("status") == "ok" and (r.get("support") or 0) < prev["summary"]["samplesPerQuestion"]]
    qfile = None
    for f in glob.glob(os.path.join(args.data_dir, "**", "*.json"), recursive=True):
        if "mini_dev" in os.path.basename(f):
            qfile = f
            break
    gold = {q["question_id"]: q["SQL"] for q in json.load(open(qfile, encoding="utf-8"))}
    db_dir = os.path.join(args.data_dir, "databases")
    if not os.path.isdir(db_dir):
        db_dir = args.data_dir
    items = [(r, gold[r["id"]]) for r in targets if r["id"] in gold]

    t0 = time.time()
    out = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(one, it, db_dir, args.data_dir) for it in items]
        for i, f in enumerate(futs):
            try:
                out.append(f.result())
            except Exception as e:  # noqa: BLE001
                out.append({"id": items[i][0]["id"], "status": "crashed", "error": str(e)[:160]})
    doc = {"summary": dict(summarise(out, n_total), wall_s=round(time.time() - t0, 1), model=H.MODEL),
           "rows": out}
    json.dump(doc, open(args.out, "w"), ensure_ascii=False)
    print(json.dumps(doc["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
