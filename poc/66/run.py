#!/usr/bin/env python3
"""POC-66: can a validator flag be turned into a repair that actually lands?

POC-64 repaired only on the two runtime signals (exec error, zero rows) and got
+2.40pp from 19% of the wrong answers. POC-65 then produced a second signal
class with 92.9% precision: structural flags on answers that ran fine.

The open question is not "does the flag fire" but "does telling the model *what
is wrong* repair more than telling it *that something might be wrong*". If the
two arms fix the same number of questions, the validator's explanation is
decoration; if the explanatory arm wins, the flag is worth writing carefully.

Design: paired, two arms per flagged wrong answer, no gold in either prompt.

  A (reason)   the validator's finding, with concrete column values for LITERAL
  B (generic)  "review the query, it may be wrong"

Order is counterbalanced by question index so a warm-cache advantage cannot
favour one arm. Scoring is execution match against gold, computed after.

Usage:
  python3 poc/66/run.py --selftest
  python3 poc/66/run.py --data-dir ~/data/bird_mini_dev --results ../65/results.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import ex  # noqa: E402
import run as H  # noqa: E402

SYSTEM = (
    "You are a text-to-SQL engine. You previously wrote a query that is wrong. "
    "Use the diagnosis to produce exactly one corrected SQLite statement, nothing else."
)


# ---------------------------------------------------------------- reasons


def _sample_values(conn, table, column, k=5):
    try:
        rows = conn.execute(
            'SELECT DISTINCT "%s" FROM "%s" WHERE "%s" IS NOT NULL LIMIT %d'
            % (column, table, column, k)).fetchall()
        return [str(r[0]) for r in rows]
    except Exception:  # noqa: BLE001
        return []


def reason_for(db_path, flags):
    """Turn a flag into the sentence a human reviewer would write.

    Values are schema data (what the column contains), never the answer to the
    question. That distinction is what keeps this legal at inference time.
    """
    import sqlite3
    from urllib.parse import quote

    parts = []
    literal_hits = ((flags or {}).get("literal") or {}).get("hits") or []
    if literal_hits:
        conn = sqlite3.connect("file:%s?mode=ro" % quote(db_path), uri=True, timeout=5.0)
        try:
            for h in literal_hits[:2]:
                vals = _sample_values(conn, h["table"], h["column"])
                if h["state"] == "case":
                    parts.append(
                        "The value %r is compared with column %s.%s, but that column only "
                        "contains it in a different case (e.g. %s). SQLite string comparison "
                        "is case-sensitive." % (h["literal"], h["table"], h["column"],
                                                ", ".join(repr(v) for v in vals[:3])))
                else:
                    parts.append(
                        "The value %r does not exist in column %s.%s (actual values include %s)."
                        % (h["literal"], h["table"], h["column"],
                           ", ".join(repr(v) for v in vals[:3]) or "none"))
        finally:
            conn.close()
    shape = (flags or {}).get("shape") or {}
    if shape.get("flag"):
        parts.append("The question asks for a single value, but the query returns %s."
                     % str(shape.get("why", "")).replace("scalar question returned ", ""))
    degen = (flags or {}).get("degenerate") or {}
    if degen.get("flag"):
        parts.append("The query returned NULL. That usually means the filter matched no rows "
                     "or a division by zero; check the filter values and the join.")
    fan = (flags or {}).get("fanout") or {}
    if fan.get("flag"):
        parts.append("The aggregate looks inflated by a one-to-many join (%s)."
                     % str(fan.get("why", ""))[:80])
    return " ".join(parts) if parts else "The query is probably wrong."


def build(card, question, sql, diagnosis, arm):
    head = "%s\nQuestion: %s\n\nPrevious SQL:\n%s\n\n" % (card, question, sql)
    if arm == "reason":
        body = head + "Diagnosis: %s\n\nCorrected SQL:" % diagnosis
    else:
        body = (head + "The previous query may be incorrect. Review it and output one "
                "corrected SQL statement.\n\nCorrected SQL:")
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": body}]


# ---------------------------------------------------------------- one repair


def solve(item, db_dir, mode, data_dir):
    row, gold_sql, idx = item
    out = {"id": row["id"], "db_id": row["db_id"], "support": row.get("support"),
           "rules": sorted([k for k, v in (row.get("flags") or {}).items()
                            if isinstance(v, dict) and v.get("flag")]),
           "arms": {}}
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
    diagnosis = reason_for(db_path, row.get("flags"))
    out["diagnosis"] = diagnosis[:400]
    # counterbalance: half the questions see the generic arm first
    order = ("reason", "generic") if idx % 2 == 0 else ("generic", "reason")
    for arm in order:
        msgs = build(card, row["question"], row["winner"]["sql"], diagnosis, arm)
        try:
            r = H.call(msgs)
        except RuntimeError as e:
            out["arms"][arm] = {"ok": False, "error": str(e)}
            continue
        sql, _f = ex.strip_fence(r["text"])
        allowed, why = ex.guard(sql)
        if not allowed:
            out["arms"][arm] = {"ok": False, "guard": why, "sql": sql}
            continue
        res = ex.execute(db_path, sql)
        if not res.ok:
            out["arms"][arm] = {"ok": False, "exec_error": (res.error or "")[:120], "sql": sql}
            continue
        m, s = ex.compare(res.rows, gold)
        out["arms"][arm] = {"ok": True, "ex_set": s, "ex_multiset": m, "rows": len(res.rows),
                            "sql": sql, "usage": r["usage"], "ms": r["ms"]}
    out["status"] = "ok"
    return out


# ---------------------------------------------------------------- stats


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p for b vs c discordant pairs."""
    import math
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def summarise(rows, total_questions):
    ok = [r for r in rows if r.get("status") == "ok"]
    a = sum(1 for r in ok if (r["arms"].get("reason") or {}).get("ex_set"))
    b = sum(1 for r in ok if (r["arms"].get("generic") or {}).get("ex_set"))
    only_a = sum(1 for r in ok if (r["arms"].get("reason") or {}).get("ex_set")
                 and not (r["arms"].get("generic") or {}).get("ex_set"))
    only_b = sum(1 for r in ok if (r["arms"].get("generic") or {}).get("ex_set")
                 and not (r["arms"].get("reason") or {}).get("ex_set"))
    by_rule = {}
    for rule in ("literal", "shape", "degenerate", "fanout"):
        grp = [r for r in ok if rule in r["rules"]]
        if grp:
            by_rule[rule] = {
                "n": len(grp),
                "reason": sum(1 for r in grp if (r["arms"].get("reason") or {}).get("ex_set")),
                "generic": sum(1 for r in grp if (r["arms"].get("generic") or {}).get("ex_set")),
            }
    return {
        "triggered": len(rows),
        "repaired_ok": len(ok),
        "totalQuestions": total_questions,
        "reason": {"fixed": a, "yield": round(a / len(ok), 4) if ok else None,
                   "netPp": round(100 * a / total_questions, 2)},
        "generic": {"fixed": b, "yield": round(b / len(ok), 4) if ok else None,
                    "netPp": round(100 * b / total_questions, 2)},
        "mcnemar": {"onlyReason": only_a, "onlyGeneric": only_b,
                    "p": round(mcnemar_exact(only_a, only_b), 6)},
        "byRule": by_rule,
        "triggerRate": round(len(rows) / total_questions, 4),
    }


# ---------------------------------------------------------------- selftest


def selftest():
    import sqlite3
    import tempfile

    tmp = tempfile.mkdtemp(prefix="poc66-")
    db = os.path.join(tmp, "t.sqlite")
    c = sqlite3.connect(db)
    c.executescript("CREATE TABLE orders(id INTEGER, status TEXT);"
                    "INSERT INTO orders VALUES (1,'paid'),(2,'refunded');")
    c.commit()
    c.close()

    flags = {"literal": {"flag": True, "checked": True,
                         "hits": [{"table": "orders", "column": "status",
                                   "literal": "PAID", "state": "case"}]},
             "shape": {"flag": False}, "degenerate": {"flag": False}, "fanout": {"flag": False}}
    r1 = reason_for(db, flags)
    flags2 = dict(flags, literal={"flag": True, "hits": [
        {"table": "orders", "column": "status", "literal": "shipped", "state": "absent"}]})
    r2 = reason_for(db, flags2)
    flags3 = {"literal": {"flag": False}, "shape": {"flag": True, "why": "scalar question returned 3 rows"},
              "degenerate": {"flag": False}, "fanout": {"flag": False}}
    r3 = reason_for(db, flags3)
    cases = [
        {"case": "case mismatch names the actual values", "pass": "paid" in r1 and "case" in r1.lower()},
        {"case": "absent value says so", "pass": "does not exist" in r2 and "paid" in r2},
        {"case": "shape explains row count", "pass": "3 rows" in r3},
        {"case": "no flags still yields a sentence", "pass": bool(reason_for(db, {}))},
    ]
    for b, cc, want in ((3, 0, 0.25), (8, 2, 0.109375), (0, 0, 1.0)):
        got = mcnemar_exact(b, cc)
        cases.append({"case": "mcnemar %d/%d" % (b, cc), "got": round(got, 6),
                      "pass": abs(got - want) < 1e-6})
    prompt = build("CARD", "Q", "SELECT 1", "D", "reason")
    cases.append({"case": "reason prompt carries the diagnosis",
                  "pass": "Diagnosis: D" in prompt[1]["content"]})
    cases.append({"case": "generic prompt hides the diagnosis",
                  "pass": "Diagnosis" not in build("CARD", "Q", "SELECT 1", "D", "generic")[1]["content"]})
    ok = all(c["pass"] for c in cases)
    return {"cases": cases, "pass": sum(1 for c in cases if c["pass"]),
            "total": len(cases), "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--results", default=os.path.join(HERE, "..", "65", "results.json"))
    ap.add_argument("--schema-mode", default="samples")
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

    prev = json.load(open(args.results))
    total = prev["summary"]["n"]
    targets = [r for r in prev["rows"]
               if r.get("status") == "ok" and not r["winner"]["ex_set"]
               and (r.get("flags") or {}).get("any")]
    if args.limit:
        targets = targets[: args.limit]

    # gold SQL comes from the dataset, never from the flags or the model
    import glob
    qfile = None
    for f in glob.glob(os.path.join(args.data_dir, "**", "*.json"), recursive=True):
        if "mini_dev" in os.path.basename(f):
            qfile = f
            break
    gold = {q["question_id"]: q["SQL"] for q in json.load(open(qfile, encoding="utf-8"))}
    db_dir = os.path.join(args.data_dir, "databases")
    if not os.path.isdir(db_dir):
        db_dir = args.data_dir

    items = [(r, gold[r["id"]], i) for i, r in enumerate(targets) if r["id"] in gold]
    t0 = time.time()
    out_rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(solve, it, db_dir, args.schema_mode, args.data_dir) for it in items]
        for i, f in enumerate(futs):
            try:
                out_rows.append(f.result())
            except Exception as e:  # noqa: BLE001
                out_rows.append({"id": items[i][0]["id"], "status": "crashed", "error": str(e)[:160]})
            if (i + 1) % 20 == 0:
                print("  %d/%d  %.0fs" % (i + 1, len(items), time.time() - t0), flush=True)

    usage = {k: sum((r.get("arms", {}).get(a, {}).get("usage", {}) or {}).get(k, 0)
                    for r in out_rows for a in ("reason", "generic"))
             for k in ("in", "out", "hit", "miss")}
    cost = (usage["miss"] * H.PRICE["in_miss"] + usage["hit"] * H.PRICE["in_hit"]
            + usage["out"] * H.PRICE["out"]) / 1e6
    doc = {"summary": dict(summarise(out_rows, total), cost_usd=round(cost, 4),
                           wall_s=round(time.time() - t0, 1), model=H.MODEL,
                           schemaMode=args.schema_mode, sourceResults=os.path.relpath(args.results, HERE)),
           "rows": out_rows}
    json.dump(doc, open(args.out, "w"), ensure_ascii=False)
    print(json.dumps(doc["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
