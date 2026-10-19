#!/usr/bin/env python3
"""POC-68: what does the whole repair pipeline actually deliver, end to end?

POC-64 repaired on runtime signals (+2.40pp) and POC-66 repaired on structural
diagnoses (+2.60pp). Their trigger sets overlap on 23 of 52 questions, so adding
the two numbers would be wrong. This script runs them as one pipeline on the
same 500 answers:

  stage 1  runtime signal   empty result / no executable SQL  -> execution feedback
  stage 2  structural flag  LITERAL / SHAPE / DEGENERATE      -> validator diagnosis

Stage 2 only sees questions that are *still wrong* after stage 1, and always
repairs the latest SQL, not the original. The reported number is the final
execution match over all 500 questions, with per-stage attribution.

No gold is used to build any prompt; gold is read once, at scoring time.

Usage:
  python3 poc/68/pipeline.py --selftest
  python3 poc/68/pipeline.py --data-dir ~/data/bird_mini_dev
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import ex  # noqa: E402
import run as H  # noqa: E402  (poc/60/run.py: call/schema_card/find_db)

# bind by explicit path: `run` is already taken by poc/60, and poc/66 exposes
# build()/reason_for() that this pipeline reuses verbatim.
sys.path.insert(0, os.path.join(HERE, "..", "65"))
import validators as V  # noqa: E402

import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location(
    "poc66_run", os.path.join(HERE, "..", "66", "run.py"))
R66 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R66)

STAGE1_SYS = (
    "You are a text-to-SQL engine. Your previous query did not work. "
    "Diagnose why and output exactly one corrected SQLite statement, nothing else."
)


def runtime_signal(row):
    """The two signals that exist without validators (POC-64)."""
    if row.get("status") == "llm_failed":
        return "exec_error"
    if row.get("status") == "ok" and (row["winner"].get("rows") or 0) == 0:
        return "empty_result"
    return None


def stage1_prompt(card, question, sql, error, signal):
    why = ("The database rejected it: %s" % (error or "")[:300]
           if signal == "exec_error" else
           "It executed successfully but returned zero rows, which is almost certainly wrong.")
    body = "%s\nQuestion: %s\n\nPrevious SQL:\n%s\n\n%s\n\nCorrected SQL:" % (
        card, question, sql or "(none)", why)
    return [{"role": "system", "content": STAGE1_SYS},
            {"role": "user", "content": body}]


def first_error(row):
    for s in row.get("samples") or []:
        if s.get("error"):
            return s["error"]
    return None


def first_sql(row):
    if row.get("winner"):
        return row["winner"]["sql"]
    for s in row.get("samples") or []:
        if s.get("sql"):
            return s["sql"]
    return ""


def one(item, db_dir, mode, data_dir):
    row, gold_sql = item
    out = {"id": row["id"], "db_id": row["db_id"], "stages": [],
           "usage": {"in": 0, "out": 0, "hit": 0, "miss": 0}}
    db_path = H.find_db(db_dir, row["db_id"])
    if not db_path:
        out["status"] = "db_missing"
        return out
    g = ex.execute(db_path, gold_sql)
    if not g.ok:
        out["status"] = "gold_error"
        return out
    gold = g.rows
    card = H.schema_card(db_path, row["db_id"], mode, data_dir, row["question"])
    sql = first_sql(row)
    correct = bool(row.get("winner", {}).get("ex_set"))
    out["baseCorrect"] = correct

    sig = runtime_signal(row)
    if sig and not correct:
        try:
            r = H.call(stage1_prompt(card, row["question"], sql, first_error(row), sig))
            for k in out["usage"]:
                out["usage"][k] += r["usage"].get(k, 0) or 0
            sql2, _f = ex.strip_fence(r["text"])
            allowed, why = ex.guard(sql2)
            res = ex.execute(db_path, sql2) if allowed else None
            fixed = bool(res and res.ok and ex.compare(res.rows, gold)[1])
            out["stages"].append({"stage": 1, "signal": sig, "ok": bool(res and res.ok),
                                  "fixed": fixed, "sql": sql2[:400]})
            if res and res.ok:
                sql = sql2
            if fixed:
                correct = True
        except RuntimeError as e:
            out["stages"].append({"stage": 1, "signal": sig, "error": str(e)})

    if not correct:
        # recompute flags on the latest SQL: after stage 1 the failure may have moved
        res0 = ex.execute(db_path, sql) if sql else None
        flags = V.validate(db_path, row["question"], sql, res0.rows if res0 and res0.ok else [])
        if flags.get("any"):
            try:
                reason = R66.reason_for(db_path, flags)
                r = H.call(R66.build(card, row["question"], sql, reason, "reason"))
                for k in out["usage"]:
                    out["usage"][k] += r["usage"].get(k, 0) or 0
                sql3, _f = ex.strip_fence(r["text"])
                allowed, why = ex.guard(sql3)
                res = ex.execute(db_path, sql3) if allowed else None
                fixed = bool(res and res.ok and ex.compare(res.rows, gold)[1])
                out["stages"].append({"stage": 2, "signal": "flag", "rules":
                                      [k for k, v in flags.items() if isinstance(v, dict) and v.get("flag")],
                                      "ok": bool(res and res.ok), "fixed": fixed, "sql": sql3[:400]})
                if fixed:
                    correct = True
            except RuntimeError as e:
                out["stages"].append({"stage": 2, "error": str(e)})
        else:
            out["stages"].append({"stage": 2, "skipped": "no flag on latest SQL"})

    out["finalCorrect"] = correct
    out["status"] = "ok"
    return out


def summarise(rows, n_total, base_correct):
    a = [r for r in rows if r.get("status") == "ok"]
    s1 = [r for r in a if any(x.get("stage") == 1 and x.get("fixed") for x in r["stages"])]
    s2 = [r for r in a if any(x.get("stage") == 2 and x.get("fixed") for x in r["stages"])]
    return {
        "n": n_total,
        "base": {"correct": base_correct, "ex": round(base_correct / n_total, 4)},
        "stage1": {"attempted": sum(1 for r in a if any(x.get("stage") == 1 for x in r["stages"])),
                   "fixed": len(s1)},
        "stage2": {"attempted": sum(1 for r in a if any(x.get("stage") == 2 and "skipped" not in x
                                                        for x in r["stages"])),
                   "fixed": len(s2)},
        "final": {"correct": base_correct + len(s1) + len(s2),
                  "ex": round((base_correct + len(s1) + len(s2)) / n_total, 4)},
        "deltaPp": round(100 * (len(s1) + len(s2)) / n_total, 2),
        "sumOfPartsPp": 2.40 + 2.60,
    }


def selftest():
    rows = [
        {"status": "ok", "winner": {"rows": 0}},
        {"status": "ok", "winner": {"rows": 3}},
        {"status": "llm_failed", "samples": [{"error": "no such column"}]},
        {"status": "gold_error"},
    ]
    got = [runtime_signal(r) for r in rows]
    want = ["empty_result", None, "exec_error", None]
    cases = [{"case": "signal selector", "got": got, "want": want, "pass": got == want}]
    p = stage1_prompt("CARD", "Q", "SELECT 1", None, "empty_result")
    cases.append({"case": "empty prompt explains zero rows",
                  "pass": "zero rows" in p[1]["content"]})
    p2 = stage1_prompt("CARD", "Q", "SELECT 1", "no such column: x", "exec_error")
    cases.append({"case": "error prompt carries the message",
                  "pass": "no such column: x" in p2[1]["content"]})
    s = summarise([{"status": "ok", "stages": [{"stage": 1, "fixed": True}, {"stage": 2, "skipped": "x"}]},
                   {"status": "ok", "stages": [{"stage": 2, "fixed": True}]}], 10, 5)
    cases.append({"case": "summary counts both stages", "got": s["final"]["correct"],
                  "pass": s["final"]["correct"] == 7 and s["stage1"]["fixed"] == 1 and s["stage2"]["fixed"] == 1})
    ok = all(c["pass"] for c in cases)
    return {"cases": cases, "pass": sum(1 for c in cases if c["pass"]), "total": len(cases), "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--results", default=os.path.join(HERE, "..", "65", "results.json"))
    ap.add_argument("--schema-mode", default="samples")
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
    base_correct = sum(1 for r in prev["rows"] if r.get("status") == "ok" and r["winner"]["ex_set"])
    qfile = None
    for f in glob.glob(os.path.join(args.data_dir, "**", "*.json"), recursive=True):
        if "mini_dev" in os.path.basename(f):
            qfile = f
            break
    gold = {q["question_id"]: q["SQL"] for q in json.load(open(qfile, encoding="utf-8"))}
    db_dir = os.path.join(args.data_dir, "databases")
    if not os.path.isdir(db_dir):
        db_dir = args.data_dir
    items = [(r, gold[r["id"]]) for r in prev["rows"] if r["id"] in gold]

    t0 = time.time()
    out = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(one, it, db_dir, args.schema_mode, args.data_dir) for it in items]
        for i, f in enumerate(futs):
            try:
                out.append(f.result())
            except Exception as e:  # noqa: BLE001
                out.append({"id": items[i][0]["id"], "status": "crashed", "error": str(e)[:160]})
            if (i + 1) % 50 == 0:
                print("  %d/%d  %.0fs" % (i + 1, len(items), time.time() - t0), flush=True)

    usage = {k: sum(r.get("usage", {}).get(k, 0) for r in out) for k in ("in", "out", "hit", "miss")}
    cost = (usage["miss"] * H.PRICE["in_miss"] + usage["hit"] * H.PRICE["in_hit"]
            + usage["out"] * H.PRICE["out"]) / 1e6
    doc = {"summary": dict(summarise(out, n_total, base_correct),
                           wall_s=round(time.time() - t0, 1), model=H.MODEL,
                           schemaMode=args.schema_mode, tokens=usage, cost_usd=round(cost, 4)),
           "rows": out}
    json.dump(doc, open(args.out, "w"), ensure_ascii=False)
    print(json.dumps(doc["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
