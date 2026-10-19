#!/usr/bin/env python3
"""POC-64: can a repair loop actually fire, and does it fix anything?

A repair loop needs a *signal* that something went wrong. At inference time we
have only two honest ones:

  1. the database rejected the SQL (syntax, unknown column, type)
  2. the SQL ran and returned zero rows

Everything else — wrong column, wrong aggregation, wrong join — runs fine and
returns a plausible-looking answer. That is exactly the 65% of failures POC-60
labelled "right shape, wrong values".

So the ceiling of any repair loop is the *trigger rate*, not the model's repair
ability. This POC measures both, in order:

  triggers  = failures where one of the two signals fires
  fixes     = triggers that become correct after exactly one repair turn
  net       = fixes / all questions   (the number that moves EX)

No gold information is used to build the repair prompt; gold is only used
afterwards to score.
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import ex  # noqa: E402
import metadata  # noqa: E402
import run as H  # noqa: E402

REPAIR_SYS = (
    "You are a text-to-SQL engine. You previously wrote a query that did not work. "
    "Diagnose why and output exactly one corrected SQLite statement, nothing else."
)


def trigger_of(status, rows, error):
    """The two signals that exist without seeing the answer."""
    if status == "exec_error":
        return "exec_error"
    if status == "guarded":
        return "guard"
    if status == "ok" and rows == 0:
        return "empty_result"
    return None


def repair_prompt(card, question, sql, kind, error):
    if kind == "exec_error":
        why = "The database rejected it: %s" % (error or "")[:300]
    elif kind == "guard":
        why = "It was rejected because only read-only statements are allowed."
    else:
        why = "It executed successfully but returned zero rows, which is almost certainly wrong."
    return [
        {"role": "system", "content": REPAIR_SYS},
        {"role": "user", "content": "%s\nQuestion: %s\n\nPrevious SQL:\n%s\n\n%s\n\nCorrected SQL:"
                                    % (card, question, sql, why)},
    ]


def solve_one(q, db_dir, mode, data_dir, do_repair=True):
    out = {"id": q["question_id"], "db_id": q["db_id"],
           "difficulty": (q.get("difficulty") or "unknown").lower()}
    db_path = H.find_db(db_dir, q["db_id"])
    if not db_path:
        out["status"] = "db_missing"
        return out
    gold = ex.execute(db_path, q["SQL"])
    out["status"] = "gold_ok" if gold.ok else "gold_error"
    if not gold.ok:
        return out

    card = H.schema_card(db_path, q["db_id"], mode, data_dir, q["question"])
    r = H.call(H.build_prompt(q, card, "off"))
    sql, _fenced = ex.strip_fence(r["text"])
    out["usage"] = {"in": r["usage"]["in"], "out": r["usage"]["out"],
                    "hit": r["usage"].get("hit", 0) or 0, "miss": r["usage"].get("miss", 0) or 0}

    allowed, why = ex.guard(sql)
    if not allowed:
        first = {"status": "guarded", "error": why, "rows": 0, "ex": False}
    else:
        run = ex.execute(db_path, sql)
        if not run.ok:
            first = {"status": "exec_error", "error": run.error, "rows": 0, "ex": False}
        else:
            m, s = ex.compare(run.rows, gold.rows)
            first = {"status": "ok", "rows": len(run.rows), "ex": s, "multiset": m}
    out.update(first=first, sql=sql)
    out["first_correct"] = bool(first.get("ex"))
    out["trigger"] = None if out["first_correct"] else trigger_of(
        first.get("status"), first.get("rows", 0), first.get("error"))

    if not do_repair or not out["trigger"]:
        out["final_correct"] = out["first_correct"]
        return out

    p = repair_prompt(card, q["question"], sql, out["trigger"], first.get("error"))
    try:
        r2 = H.call(p)
    except RuntimeError as e:
        out.update(repair_error=str(e), final_correct=out["first_correct"])
        return out
    sql2, _f = ex.strip_fence(r2["text"])
    out["repair"] = {"in": r2["usage"]["in"], "out": r2["usage"]["out"],
                     "hit": r2["usage"].get("hit", 0) or 0, "miss": r2["usage"].get("miss", 0)}
    out["sql2"] = sql2
    allowed2, why2 = ex.guard(sql2)
    if not allowed2:
        out.update(repair_status="guarded", final_correct=out["first_correct"])
        return out
    run2 = ex.execute(db_path, sql2)
    if not run2.ok:
        out.update(repair_status="exec_error", final_correct=out["first_correct"])
        return out
    m2, s2 = ex.compare(run2.rows, gold.rows)
    out.update(repair_status="ok", repair_rows=len(run2.rows),
               final_correct=bool(s2), repaired=s2 and not out["first_correct"])
    return out


def summarize(rows, label=""):
    n = len(rows)
    first = sum(1 for r in rows if r.get("first_correct"))
    final = sum(1 for r in rows if r.get("final_correct"))
    wrong = [r for r in rows if not r.get("first_correct")]
    trig = [r for r in wrong if r.get("trigger")]
    fixed = [r for r in trig if r.get("repaired")]
    by_kind = {}
    for r in trig:
        k = r["trigger"]
        b = by_kind.setdefault(k, {"n": 0, "fixed": 0})
        b["n"] += 1
        b["fixed"] += 1 if r.get("repaired") else 0
    for k, b in by_kind.items():
        b["fix_rate"] = round(b["fixed"] / b["n"], 4) if b["n"] else 0.0
    return {
        "label": label, "n": n,
        "first_ex": round(first / n, 4) if n else 0.0,
        "final_ex": round(final / n, 4) if n else 0.0,
        "delta_pp": round((final - first) / n * 100, 2) if n else 0.0,
        "wrong": len(wrong),
        "with_trigger": len(trig),
        "trigger_rate": round(len(trig) / len(wrong), 4) if wrong else 0.0,
        "repaired": len(fixed),
        "repair_yield": round(len(fixed) / len(trig), 4) if trig else 0.0,
        "byTrigger": by_kind,
        "silent_wrong": len(wrong) - len(trig),
    }


def selftest():
    """The trigger classifier decides the ceiling, so it must be able to fail."""
    cases = [
        (("exec_error", 0, "no such column"), "exec_error"),
        (("ok", 0, None), "empty_result"),
        (("ok", 5, None), None),
        (("guarded", 0, "GUARD_NOT_READ_ONLY"), "guard"),
    ]
    out = [{"case": "%s/%s" % (s, r), "pass": trigger_of(s, r, e) == want}
           for (s, r, e), want in cases]
    return {"checks": out, "pass": sum(1 for x in out if x["pass"]), "total": len(out),
            "ok": all(x["pass"] for x in out)}


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/data/bird_mini_dev")
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    if not (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY")):
        print("DEEPSEEK_API_KEY is not set", file=sys.stderr)
        return 2
    qfile = os.path.join(data_dir, "data", "mini_dev_sqlite-00000-of-00001.json")
    if not os.path.exists(qfile):
        for root, _d, files in os.walk(data_dir):
            for f in files:
                if f.endswith(".json") and "mini_dev" in f:
                    qfile = os.path.join(root, f)
                    break
    qs = json.load(open(qfile, encoding="utf-8"))
    if limit and limit < len(qs):
        qs = qs[:limit]
    db_dir = os.path.join(data_dir, "databases")

    st = selftest()
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda q: solve_one(q, db_dir, "samples", data_dir), qs))
    rep = summarize(rows, "repair-once")
    rep["selftest"] = {"pass": st["pass"], "total": st["total"], "ok": st["ok"]}
    rep["ok"] = st["ok"]
    json.dump({"summary": rep, "rows": rows}, open(os.path.join(HERE, "results.json"), "w"),
              ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
