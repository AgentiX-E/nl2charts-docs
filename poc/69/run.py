#!/usr/bin/env python3
"""POC-69: does writing a plan before the SQL buy accuracy, or just tokens?

Every remaining lever on our list changes the *prompt*. Plan-then-SQL is the
cheapest such lever that the literature keeps recommending, and it is also the
easiest to fool yourself about: the model writes more text, the answer looks
more considered, and nobody checks whether execution match moved.

This is a paired, single-variable experiment on the same 500 questions, same
schema card, same model, same temperature:

  arm D  direct        the POC-60 prompt (card + question + "SQL:")
  arm P  plan-first    same prompt, but the model must first state a 3-line plan
                       (tables, filters, aggregation) and then emit "SQL:"

Only the instruction differs; the schema text is byte-identical, so a cache hit
is still a cache hit. Scoring is execution match, computed after both arms have
answered.

Usage:
  python3 poc/69/run.py --selftest
  python3 poc/69/run.py --data-dir ~/data/bird_mini_dev --limit 500
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
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import ex  # noqa: E402
import run as H  # noqa: E402

PLAN_SYS = (
    "You are a text-to-SQL engine. First write a plan of at most three lines: "
    "which tables, which filters, which aggregation. Then output a line starting "
    "with SQL: followed by exactly one SQLite statement."
)
PLAN_HINT = (
    "Plan (max 3 lines), then a line 'SQL:' with one SQLite statement."
)


def parse_plan(text):
    """Split model output into (plan, sql). Robust to fences and stray 'SQL:'."""
    t = (text or "").strip()
    m = re.search(r"(?im)^\s*SQL\s*:\s*", t)
    if not m:
        # some models put it inline: "... SQL: SELECT ..."
        m = re.search(r"(?i)\bSQL\s*:\s*", t)
    if m:
        plan, sql = t[: m.start()], t[m.end():]
    else:
        plan, sql = "", t
    sql, _f = ex.strip_fence(sql)
    sql = sql.strip().split("\n\n")[0].strip()
    return plan.strip(), sql


def plan_prompt(q, card):
    user = [card, "", PLAN_HINT, "", "Question: %s" % q["question"]]
    return [{"role": "system", "content": PLAN_SYS},
            {"role": "user", "content": "\n".join(user)}]


def run_one(q, db_dir, data_dir):
    out = {"id": q["question_id"], "db_id": q["db_id"],
           "difficulty": (q.get("difficulty") or "unknown").lower()}
    db_path = H.find_db(db_dir, q["db_id"])
    if not db_path:
        out["status"] = "db_missing"
        return out
    gold = ex.execute(db_path, q["SQL"])
    if not gold.ok:
        out["status"] = "gold_error"
        return out
    card = H.schema_card(db_path, q["db_id"], "samples", data_dir, q["question"])
    out["cardChars"] = len(card)
    arms = {}
    for arm, msgs in (("direct", H.build_prompt(q, card, "off")),
                      ("plan", plan_prompt(q, card))):
        try:
            r = H.call(msgs, max_tokens=600 if arm == "plan" else 400)
        except RuntimeError as e:
            arms[arm] = {"ok": False, "error": str(e)}
            continue
        if arm == "plan":
            plan, sql = parse_plan(r["text"])
        else:
            plan, sql = "", ex.strip_fence(r["text"])[0]
        allowed, why = ex.guard(sql)
        if not allowed:
            arms[arm] = {"ok": False, "guard": why, "sql": sql, "plan": plan}
            continue
        res = ex.execute(db_path, sql)
        if not res.ok:
            arms[arm] = {"ok": False, "exec_error": (res.error or "")[:120],
                         "sql": sql, "plan": plan}
            continue
        m, s = ex.compare(res.rows, gold.rows)
        arms[arm] = {"ok": True, "ex_set": s, "ex_multiset": m,
                     "sql": sql, "plan": plan, "rows": len(res.rows),
                     "usage": r["usage"], "ms": r["ms"]}
    out["arms"] = arms
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
    ok = [r for r in rows if r.get("status") == "ok"]
    d = sum(1 for r in ok if (r["arms"].get("direct") or {}).get("ex_set"))
    p = sum(1 for r in ok if (r["arms"].get("plan") or {}).get("ex_set"))
    only_p = sum(1 for r in ok if (r["arms"].get("plan") or {}).get("ex_set")
                 and not (r["arms"].get("direct") or {}).get("ex_set"))
    only_d = sum(1 for r in ok if (r["arms"].get("direct") or {}).get("ex_set")
                 and not (r["arms"].get("plan") or {}).get("ex_set"))
    by = {}
    for diff in ("simple", "moderate", "challenging"):
        grp = [r for r in ok if r["difficulty"] == diff]
        if grp:
            by[diff] = {"n": len(grp),
                        "direct": sum(1 for r in grp if (r["arms"].get("direct") or {}).get("ex_set")),
                        "plan": sum(1 for r in grp if (r["arms"].get("plan") or {}).get("ex_set"))}
    usage = {}
    for arm in ("direct", "plan"):
        usage[arm] = {k: sum(((r["arms"].get(arm) or {}).get("usage") or {}).get(k, 0)
                             for r in ok) for k in ("in", "out", "hit", "miss")}
    cost = {}
    for arm in ("direct", "plan"):
        u = usage[arm]
        cost[arm] = round((u["miss"] * H.PRICE["in_miss"] + u["hit"] * H.PRICE["in_hit"]
                           + u["out"] * H.PRICE["out"]) / 1e6, 4)
    return {
        "n": n_total, "scored": len(ok),
        "direct": {"correct": d, "ex": round(d / n_total, 4)},
        "plan": {"correct": p, "ex": round(p / n_total, 4)},
        "deltaPp": round(100 * (p - d) / n_total, 2),
        "mcnemar": {"onlyPlan": only_p, "onlyDirect": only_d,
                    "p": round(mcnemar_exact(only_p, only_d), 6)},
        "byDifficulty": by, "usage": usage, "cost_usd": cost,
        "answerChars": {"direct": sum(len((r["arms"].get("direct") or {}).get("sql") or "") for r in ok),
                        "plan": sum(len((r["arms"].get("plan") or {}).get("sql") or "") for r in ok)},
    }


def selftest():
    cases = []
    for label, text, want_sql, want_plan_has in (
        ("sql line", "1. join users\n2. filter paid\nSQL:\nSELECT 1", "SELECT 1", "join"),
        ("inline sql", "plan: count rows SQL: SELECT COUNT(*) FROM t", "SELECT COUNT(*) FROM t", "count"),
        ("fenced sql", "plan\nSQL:\n```sql\nSELECT 2\n```", "SELECT 2", "plan"),
        ("no marker", "SELECT 3", "SELECT 3", ""),
        ("sql word in plan", "plan: use SQL: semantics\nSQL:\nSELECT 4", "SELECT 4", "semantics"),
    ):
        plan, sql = parse_plan(text)
        cases.append({"case": label, "sql": sql, "pass": sql == want_sql and want_plan_has in plan})
    for b, c, want in ((4, 0, 0.125), (6, 2, 0.289062), (0, 0, 1.0)):
        got = mcnemar_exact(b, c)
        cases.append({"case": "mcnemar %d/%d" % (b, c), "got": round(got, 6),
                      "pass": abs(got - want) < 1e-6})
    ok = all(c["pass"] for c in cases)
    return {"cases": cases, "pass": sum(1 for c in cases if c["pass"]),
            "total": len(cases), "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--limit", type=int, default=0)
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

    qfile = None
    for f in glob.glob(os.path.join(args.data_dir, "**", "*.json"), recursive=True):
        if "mini_dev" in os.path.basename(f):
            qfile = f
            break
    qs = json.load(open(qfile, encoding="utf-8"))
    if args.limit:
        qs = qs[: args.limit]
    db_dir = os.path.join(args.data_dir, "databases")
    if not os.path.isdir(db_dir):
        db_dir = args.data_dir

    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(run_one, q, db_dir, args.data_dir) for q in qs]
        for i, f in enumerate(futs):
            try:
                rows.append(f.result())
            except Exception as e:  # noqa: BLE001
                rows.append({"id": qs[i]["question_id"], "status": "crashed", "error": str(e)[:160]})
            if (i + 1) % 50 == 0:
                print("  %d/%d  %.0fs" % (i + 1, len(qs), time.time() - t0), flush=True)

    doc = {"summary": dict(summarise(rows, len(qs)),
                           wall_s=round(time.time() - t0, 1), model=H.MODEL),
           "rows": rows}
    json.dump(doc, open(args.out, "w"), ensure_ascii=False)
    print(json.dumps(doc["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
