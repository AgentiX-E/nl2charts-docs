#!/usr/bin/env python3
"""POC-78: is the gold standard unique? Same gold SQL, two engines, one verdict.

Every number this project has published rests on a hidden assumption: that
"execution match" is a property of the question and the prediction, not of the
engine that happened to run it. Our product does not make that assumption — it
ships DuckDB (WASM and Node), an optional better-sqlite3 adapter and a PostgreSQL
connector, and §2.5 already says the same query may execute on any of them.

So the assumption is testable, and cheaply: take the 500 BIRD Mini-Dev gold SQL
statements, run each on SQLite and on DuckDB (attaching the same file through
DuckDB's sqlite extension, CPU only), and ask two questions.

  1. Does the *gold itself* produce the same result set on both engines?
  2. Does the *verdict* on a prediction flip between engines?

A flip is not a curiosity. It means a user who switches adapter sees a different
answer, and it means any accuracy figure has to name its engine (this becomes
EV9). A gold that disagrees with itself cannot arbitrate anything.

Usage:
  python3 poc/78/run.py --results poc/65/results.json --data-dir /root/data/bird_mini_dev
  python3 poc/78/run.py --selftest
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import ex  # noqa: E402

# BIRD gold is SQLite dialect. DuckDB accepts most of it, and the places it does
# not are themselves the finding, so they are classified rather than retried.
DIALECT_HINTS = re.compile(
    r"\b(julianday|strftime|datetime|date|substr|printf|group_concat|ifnull|"
    r"instr|typeof|randomblob|last_insert_rowid)\s*\(", re.I)


def find_dbs(data_dir: str) -> dict[str, str]:
    out = {}
    for p in glob.glob(os.path.join(data_dir, "databases", "database", "*", "*.sqlite")):
        out[os.path.basename(os.path.dirname(p))] = p
    return out


def load_questions(data_dir: str) -> list[dict]:
    f = glob.glob(os.path.join(data_dir, "data", "mini_dev*.json"))
    if not f:
        return []
    return json.load(open(f[0], encoding="utf-8"))


# The gap is dominated by one function: DuckDB has no `iif`, and 54 of the 104
# failures use it. A single macro is the whole shim, which is why the adapter
# needs a compatibility preamble rather than a query rewriter.
SHIM = ("CREATE MACRO IF NOT EXISTS iif(c, a, b) AS CASE WHEN c THEN a ELSE b END;")


def import_tables(con) -> int:
    """Strategy B: copy every table into the engine's own catalog.

    A macro cannot be created in the read-only attached catalog, and DuckDB
    resolves macros per schema — so with `USE db` the shim is invisible, and
    without it the tables are. Importing the tables into `main` is the only way
    to have both, at the cost of materialising the data.
    """
    names = [r[0] for r in con.execute(
        "select table_name from information_schema.tables where table_catalog='db'").fetchall()]
    for n in names:
        con.execute(f'CREATE TABLE main."{n}" AS SELECT * FROM db."{n}"')
    return len(names)


def run_duck(db_path: str, sql: str, timeout_s: float = 30.0, shim: bool = False,
             import_into_main: bool = False):
    import duckdb
    t0 = time.perf_counter()
    con = None
    try:
        con = duckdb.connect()
        con.execute("INSTALL sqlite; LOAD sqlite;")
        con.execute("SET threads=2")
        con.execute(f"ATTACH '{db_path}' AS db (TYPE SQLITE, READ_ONLY)")
        # The gold writes bare table names. Without USE the attached catalog is
        # only reachable as `db.table`, and every statement fails on binding —
        # which is precisely the kind of adapter concern this POC is about.
        if import_into_main:
            n = import_tables(con)
            if shim:
                con.execute(SHIM)
            if n == 0:
                raise RuntimeError("no tables imported")
        else:
            # Macros are schema-scoped: created in `main`, they are invisible
            # once `USE db` points at the attached catalog. This is why the
            # import strategy exists at all.
            if shim:
                con.execute(SHIM)
            con.execute("USE db")
        cur = con.execute(sql)
        rows = cur.fetchall()
        return {"ok": True, "rows": rows, "ms": (time.perf_counter() - t0) * 1000}
    except Exception as e:  # noqa: BLE001 - the message is the evidence
        return {"ok": False, "rows": [], "error": "%s: %s" % (type(e).__name__, str(e)[:160]),
                "ms": (time.perf_counter() - t0) * 1000}
    finally:
        if con is not None:
            con.close()


def run_sqlite(db_path: str, sql: str):
    r = ex.execute(db_path, sql)
    return {"ok": r.ok, "rows": r.rows, "error": r.error, "ms": r.ms}


def classify(err: str) -> str:
    e = (err or "").lower()
    if "parser" in e or "syntax" in e or "binder" in e or "not found" in e or "does not exist" in e:
        return "dialect"
    if "timeout" in e or "interrupt" in e:
        return "timeout"
    return "runtime"


def verdict(pred_rows, gold_rows):
    m, _s = ex.compare(pred_rows, gold_rows)
    return m


def one(q, db_path, pred_sql, shim=False, imp=False):
    gold = q.get("SQL") or ""
    out = {"id": q.get("question_id"), "db": q.get("db_id")}
    g_s = run_sqlite(db_path, gold)
    g_d = run_duck(db_path, gold, shim=shim, import_into_main=imp)
    out["goldOk_sqlite"] = g_s["ok"]
    out["goldOk_duck"] = g_d["ok"]
    if not g_d["ok"]:
        out["duckError"] = classify(g_d.get("error") or "")
        out["duckDialectHint"] = bool(DIALECT_HINTS.search(gold))
    out["goldSelfConsistent"] = (bool(g_s["ok"]) and bool(g_d["ok"])
                                and verdict(g_s["rows"], g_d["rows"]))
    out["goldRows_duck"] = len(g_d["rows"]) if g_d["ok"] else None

    if pred_sql and g_s["ok"]:
        p_s = run_sqlite(db_path, pred_sql)
        out["predOk_sqlite"] = p_s["ok"]
        out["ex_sqlite"] = bool(p_s["ok"]) and verdict(p_s["rows"], g_s["rows"])
    if pred_sql and g_d["ok"]:
        p_d = run_duck(db_path, pred_sql, shim=shim, import_into_main=imp)
        out["predOk_duck"] = p_d["ok"]
        out["ex_duck"] = bool(p_d["ok"]) and verdict(p_d["rows"], g_d["rows"])
        if not p_d["ok"]:
            out["predDuckError"] = classify(p_d.get("error") or "")
    return out


def summarise(rows, wall):
    both = [r for r in rows if r.get("ex_sqlite") is not None and r.get("ex_duck") is not None]
    flips_s = [r for r in both if r["ex_sqlite"] and not r["ex_duck"]]
    flips_d = [r for r in both if r["ex_duck"] and not r["ex_sqlite"]]
    ag = sum(1 for r in both if r["ex_sqlite"] == r["ex_duck"]) / len(both) if both else None
    gold_both = [r for r in rows if r["goldOk_sqlite"] and r["goldOk_duck"]]
    gold_agree = sum(1 for r in gold_both if r["goldSelfConsistent"]) / len(gold_both) if gold_both else None
    n = len(both)
    p = None
    if flips_s or flips_d:
        from math import comb
        k = min(len(flips_s), len(flips_d))
        tot = len(flips_s) + len(flips_d)
        p = min(1.0, 2 * sum(comb(tot, i) for i in range(0, k + 1)) / 2 ** tot)
    return {
        "n": len(rows), "nComparable": n,
        "ex_sqlite": round(sum(1 for r in both if r["ex_sqlite"]) / n, 4) if n else None,
        "ex_duck": round(sum(1 for r in both if r["ex_duck"]) / n, 4) if n else None,
        "verdictAgreement": round(ag, 4) if ag is not None else None,
        "flipsSqliteOnly": len(flips_s), "flipsDuckOnly": len(flips_d),
        "mcnemarP": round(p, 4) if p is not None else None,
        "goldRunsBoth": len(gold_both),
        "goldSelfConsistency": round(gold_agree, 4) if gold_agree is not None else None,
        "goldDuckFail": sum(1 for r in rows if not r["goldOk_duck"]),
        "goldDuckFailDialect": sum(1 for r in rows if r.get("duckError") == "dialect"),
        "predDuckFail": sum(1 for r in both if r.get("predOk_duck") is False),
        "wall_s": round(wall, 1),
    }


def selftest() -> int:
    muts = []
    muts.append({"mutation": "classify-parser", "caught": classify("duckdb.ParserException: syntax error") == "dialect"})
    muts.append({"mutation": "classify-binder", "caught": classify("Binder Error: Table x does not exist") == "dialect"})
    muts.append({"mutation": "classify-timeout", "caught": classify("Interrupt: timeout") == "timeout"})
    muts.append({"mutation": "classify-runtime", "caught": classify("division by zero") == "runtime"})
    muts.append({"mutation": "dialect-hint-julianday", "caught": bool(DIALECT_HINTS.search("select julianday('2020-01-01')"))})
    muts.append({"mutation": "dialect-hint-none", "caught": not DIALECT_HINTS.search("select count(*) from t")})
    # verdict must treat a rounded float as equal and a different count as not
    muts.append({"mutation": "verdict-round", "caught": verdict([(1.0000001,)], [(1.0,)])})
    muts.append({"mutation": "verdict-count", "caught": not verdict([(1,), (2,)], [(1,)])})
    # summarise must count a one-way flip, not average it away
    fake = [{"ex_sqlite": True, "ex_duck": False, "goldOk_sqlite": True, "goldOk_duck": True,
             "goldSelfConsistent": True},
            {"ex_sqlite": False, "ex_duck": False, "goldOk_sqlite": True, "goldOk_duck": True,
             "goldSelfConsistent": True}]
    s = summarise(fake, 0.0)
    muts.append({"mutation": "summary-flip-counted", "caught": s["flipsSqliteOnly"] == 1 and s["verdictAgreement"] == 0.5})
    ok = all(m["caught"] for m in muts)
    print(json.dumps({"selftest": muts, "ok": ok}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(HERE, "..", "65", "results.json"))
    ap.add_argument("--data-dir", default="/root/data/bird_mini_dev")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--shim", action="store_true")
    ap.add_argument("--import", dest="imp", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    dbs = find_dbs(args.data_dir)
    qs = {q["question_id"]: q for q in load_questions(args.data_dir)}
    res = json.load(open(os.path.abspath(args.results), encoding="utf-8"))
    preds = {r["id"]: (r.get("winner") or {}).get("sql") for r in res.get("rows") or []
             if r.get("status") == "ok"}
    ids = [qid for qid in preds if qid in qs and qs[qid]["db_id"] in dbs]
    if args.limit:
        ids = ids[:args.limit]

    t0 = time.time()
    def work(qid):
        q = qs[qid]
        try:
            return one(q, dbs[q["db_id"]], preds[qid], shim=args.shim, imp=args.imp)
        except Exception as e:  # noqa: BLE001
            return {"id": qid, "db": q["db_id"], "error": str(e)[:120],
                    "goldOk_sqlite": False, "goldOk_duck": False}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        out = list(pool.map(work, ids))

    summary = summarise(out, time.time() - t0)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.out:
        json.dump({"summary": summary, "rows": out}, open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
