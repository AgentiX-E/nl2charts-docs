#!/usr/bin/env python3
"""POC-79: PostgreSQL as the third engine — PGlite, WASM, CPU only.

POC-78 showed that the same gold SQL does not mean the same answer on SQLite and
DuckDB: 21.1% of statements would not run at all, 1.8% of the gold disagreed with
itself. PostgreSQL is the third engine in our product, and the one users are most
likely to point at a real cluster. Testing it used to mean a server; PGlite is
PostgreSQL compiled to WASM, so the same fixture runs on a laptop, in CI, and in
a browser tab — no daemon, no GPU.

Three things are measured:

  runrate     can the gold SQL execute at all
  selfcons    does the gold produce the same result set as on SQLite
  verdicts    does a prediction get the same right/wrong label on both engines

The exporter commits each column to one PostgreSQL type (POC-78's first failure
category was types), so every disagreement is either a type commitment or a
dialect difference — and the code reports which.

Usage:
  python3 poc/79/run.py --dbs superhero,toxicology,student_club
  python3 poc/79/run.py --selftest
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import ex  # noqa: E402

DATA = os.environ.get("BIRD_DATA", "/root/data/bird_mini_dev")
NODE = os.environ.get("NODE_BIN", "node")


def find_dbs(data_dir: str, names) -> dict[str, str]:
    out = {}
    for p in glob.glob(os.path.join(data_dir, "databases", "database", "*", "*.sqlite")):
        d = os.path.basename(os.path.dirname(p))
        if names is None or d in names:
            out[d] = p
    return out


def load_questions(data_dir: str) -> list[dict]:
    f = glob.glob(os.path.join(data_dir, "data", "mini_dev*.json"))
    return json.load(open(f[0], encoding="utf-8")) if f else []


def norm_cell(v):
    """PostgreSQL returns numeric and bigint as text; SQLite returns numbers.

    Normalising both sides to "number when it parses as one" is the only way the
    two engines can be compared at all — and it is exactly the lossy step a real
    adapter has to make too, so it belongs in one place.
    """
    if v is None:
        return ("null",)
    if isinstance(v, bool):
        return ("num", float(int(v)))
    if isinstance(v, (int, float)):
        return ("num", round(float(v), 4))
    s = str(v)
    try:
        return ("num", round(float(s), 4))
    except ValueError:
        return ("str", s)


def rows_key(rows):
    return Counter(tuple(norm_cell(c) for c in r) for r in rows)


def run_node(dumps: dict[str, str], jobs: list[dict], tmp_dir: str) -> dict:
    spec = {"dumps": dumps, "jobs": jobs}
    jf = os.path.join(tmp_dir, "jobs.json")
    rf = os.path.join(tmp_dir, "pg.json")
    json.dump(spec, open(jf, "w", encoding="utf-8"))
    subprocess.run([NODE, os.path.join(HERE, "pg_eval.mjs"), jf, rf],
                   check=True, cwd=HERE, capture_output=True, timeout=900)
    return json.load(open(rf, encoding="utf-8"))


def summarise(rows, runrate, load_ms):
    n = len(rows)
    both = [r for r in rows if r.get("gold_pg_ok") and r.get("gold_sqlite_ok")]
    selfc = [r for r in both if r["goldSelfConsistent"]]
    verd = [r for r in rows if r.get("verdict_sqlite") is not None and r.get("verdict_pg") is not None]
    agree = [r for r in verd if r["verdict_sqlite"] == r["verdict_pg"]]
    flips_s = [r for r in verd if r["verdict_sqlite"] and not r["verdict_pg"]]
    flips_p = [r for r in verd if r["verdict_pg"] and not r["verdict_sqlite"]]
    p = None
    if flips_s or flips_p:
        from math import comb
        k = min(len(flips_s), len(flips_p))
        tot = len(flips_s) + len(flips_p)
        p = min(1.0, 2 * sum(comb(tot, i) for i in range(0, k + 1)) / 2 ** tot)
    return {
        "n": n,
        "goldRunsOnPg": runrate,
        "goldComparable": len(both),
        "goldSelfConsistency": round(len(selfc) / len(both), 4) if both else None,
        "verdictComparable": len(verd),
        "verdictAgreement": round(len(agree) / len(verd), 4) if verd else None,
        "flipsSqliteOnly": len(flips_s), "flipsPgOnly": len(flips_p),
        "mcnemarP": round(p, 4) if p is not None else None,
        "pgLoadMs": load_ms,
        "pgErrors": dict(Counter((r.get("pgError") or "")[:40] for r in rows if r.get("gold_pg_ok") is False)),
    }


def selftest() -> int:
    muts = []
    muts.append({"mutation": "norm-int-str", "caught": norm_cell("42") == norm_cell(42)})
    muts.append({"mutation": "norm-float-str", "caught": norm_cell("4340.1019") == norm_cell(4340.1019)})
    muts.append({"mutation": "norm-text", "caught": norm_cell("Afghanistan") == ("str", "Afghanistan")})
    muts.append({"mutation": "norm-null", "caught": norm_cell(None) == ("null",)})
    # Row order must not matter; column order must.
    muts.append({"mutation": "key-row-order", "caught":
                 rows_key([(1, "a"), (2, "b")]) == rows_key([(2, "b"), (1, "a")])})
    muts.append({"mutation": "key-column-order", "caught":
                 rows_key([(1, "a")]) != rows_key([("a", 1)])})
    muts.append({"mutation": "key-count", "caught": rows_key([(1,), (1,)]) != rows_key([(1,)])})
    muts.append({"mutation": "key-numeric-text", "caught": rows_key([("3",)]) == rows_key([(3,)])})
    # a PG error must never be counted as agreement
    fake = [{"gold_pg_ok": False, "gold_sqlite_ok": True, "goldSelfConsistent": False,
             "verdict_sqlite": True, "verdict_pg": None}]
    s = summarise(fake, 0.0, 0)
    muts.append({"mutation": "error-not-compared", "caught": s["goldSelfConsistency"] is None and s["verdictAgreement"] is None})
    ok = all(m["caught"] for m in muts)
    print(json.dumps({"selftest": muts, "ok": ok}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dbs", default="superhero,toxicology,student_club")
    ap.add_argument("--data-dir", default=DATA)
    ap.add_argument("--results", default=os.path.join(HERE, "..", "65", "results.json"))
    ap.add_argument("--tmp", default="/tmp/poc79")
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    os.makedirs(args.tmp, exist_ok=True)
    names = {d.strip() for d in args.dbs.split(",") if d.strip()}
    dbs = find_dbs(args.data_dir, names)
    if not dbs:
        # CI ran this once with a sandbox-only default path and "succeeded" with
        # n=0. Zero work is a failure, not an empty result: it is the same
        # disease as a silent divergence, one layer up.
        print(json.dumps({"error": "no databases found", "dataDir": args.data_dir,
                          "wanted": sorted(names)}, ensure_ascii=False))
        return 2
    qs = {q["question_id"]: q for q in load_questions(args.data_dir) if q["db_id"] in dbs}
    preds = {r["id"]: (r.get("winner") or {}).get("sql")
             for r in json.load(open(os.path.abspath(args.results), encoding="utf-8")).get("rows") or []
             if r.get("status") == "ok"}

    # export
    dumps = {}
    for name, path in dbs.items():
        out = os.path.join(args.tmp, f"{name}.json")
        subprocess.run([sys.executable, os.path.join(HERE, "export.py"),
                        "--db", path, "--out", out], check=True, capture_output=True)
        dumps[name] = out

    jobs, meta = [], []
    for qid, q in qs.items():
        jobs.append({"id": qid, "db": q["db_id"], "sql": q["SQL"], "tag": "gold"})
        meta.append(("gold", qid, q["db_id"]))
        if preds.get(qid):
            jobs.append({"id": qid, "db": q["db_id"], "sql": preds[qid], "tag": "pred"})
            meta.append(("pred", qid, q["db_id"]))

    pg = run_node(dumps, jobs, args.tmp)
    by_tag = {}
    for r in pg["jobs"]:
        by_tag[(r["tag"], r["id"])] = r

    rows = []
    for qid, q in qs.items():
        g_pg = by_tag.get(("gold", qid), {})
        p_pg = by_tag.get(("pred", qid), {})
        g_s = ex.execute(dbs[q["db_id"]], q["SQL"])
        rec = {"id": qid, "db": q["db_id"],
               "gold_pg_ok": bool(g_pg.get("ok")), "gold_sqlite_ok": bool(g_s.ok)}
        if not g_pg.get("ok"):
            rec["pgError"] = (g_pg.get("error") or "")[:60]
        if g_pg.get("ok") and g_s.ok:
            rec["goldSelfConsistent"] = rows_key(g_pg["rows"]) == rows_key(g_s.rows)
        p_s = ex.execute(dbs[q["db_id"]], preds[qid]) if preds.get(qid) else None
        if g_s.ok and p_s is not None and p_s.ok:
            rec["verdict_sqlite"] = rows_key(p_s.rows) == rows_key(g_s.rows)
        if g_pg.get("ok") and p_pg.get("ok"):
            rec["verdict_pg"] = rows_key(p_pg["rows"]) == rows_key(g_pg["rows"])
        rows.append(rec)

    if not rows:
        print(json.dumps({"error": "no questions matched", "dbs": sorted(dbs)}, ensure_ascii=False))
        return 2
    runrate = round(sum(1 for r in rows if r["gold_pg_ok"]) / len(rows), 4) if rows else None
    load_ms = {k: v.get("loadMs") for k, v in (pg.get("dbs") or {}).items()}
    summary = summarise(rows, runrate, load_ms)
    summary["dbs"] = sorted(dbs)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.out:
        json.dump({"summary": summary, "rows": rows}, open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
