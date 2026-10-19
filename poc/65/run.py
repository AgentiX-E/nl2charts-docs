#!/usr/bin/env python3
"""POC-65: do gold-free checks give the silent 81% an entry point?

POC-64's conclusion was structural: a repair loop can only act on failures that
produce a signal, and 81% of wrong answers produce none. This POC asks whether
a second, independent mechanism can manufacture a signal that does not exist at
runtime:

  confidence  how many of the N samples produce the same *result set*
  validators  SHAPE / FANOUT / LITERAL / DEGENERATE (see validators.py)

Both are gold-free: they look at the question, the SQL, the schema and the
result. Gold is used once, at the end, to score — never to build the signal.

The output is the pair a product needs and a single accuracy number hides:
`coverage` (share of questions answered without a human) and `accuracy at that
coverage`. Escalating everything gives 100% review load; answering everything
gives the baseline. The frontier between them is the HITL routing policy.

Usage:
  python3 poc/65/run.py --selftest
  python3 poc/65/run.py --data-dir ~/data/bird_mini_dev --limit 500 --samples 5
  python3 poc/65/analyze.py poc/65/results.json
"""
from __future__ import annotations

import argparse
import hashlib
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
import validators as V  # noqa: E402


def signature(rows) -> str:
    """Order-insensitive, duplicate-sensitive hash of a result set.

    Result-level agreement is the semantic notion: two different SQL strings
    that return the same table are the same answer to the user. SQL-text
    agreement would understate confidence and report a repair as disagreement.
    """
    key = repr(sorted(ex.canon_rows(rows)))
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def vote(samples):
    """Pick the modal result signature; ties resolve to the earliest sample."""
    sigs = [s["sig"] for s in samples if s.get("sig")]
    if not sigs:
        return None, 0, None
    counts = Counter(sigs)
    best = max(counts.values())
    win = next(x for x in sigs if counts[x] == best)
    first = next(i for i, s in enumerate(samples) if s.get("sig") == win)
    return win, best, first


def solve_one(q, db_dir, mode, data_dir, n_samples, evidence):
    out = {"id": q["question_id"], "db_id": q["db_id"],
           "difficulty": (q.get("difficulty") or "unknown").lower(),
           "question": q["question"]}
    db_path = H.find_db(db_dir, q["db_id"])
    if not db_path:
        out["status"] = "db_missing"
        return out
    gold = ex.execute(db_path, q["SQL"])
    out["gold_ok"] = gold.ok
    if not gold.ok:
        out["status"] = "gold_error"
        return out

    card = H.schema_card(db_path, q["db_id"], mode, data_dir, q["question"])
    out["cardChars"] = len(card)
    msgs = H.build_prompt(q, card, evidence)

    samples, usage = [], {"in": 0, "out": 0, "hit": 0, "miss": 0}
    for _ in range(n_samples):
        try:
            r = H.call(msgs)
        except RuntimeError as e:
            samples.append({"sql": "", "guard": str(e), "exec": False, "sig": None,
                            "ex_set": None, "rows": 0, "ncols": 0, "ms": 0})
            continue
        for k in usage:
            usage[k] += r["usage"].get(k, 0) or 0
        sql, _fenced = ex.strip_fence(r["text"])
        allowed, why = ex.guard(sql)
        if not allowed:
            samples.append({"sql": sql, "guard": why, "exec": False, "sig": None,
                            "ex_set": None, "rows": 0, "ncols": 0, "ms": r["ms"]})
            continue
        res = ex.execute(db_path, sql)
        if not res.ok:
            samples.append({"sql": sql, "guard": None, "exec": False,
                            "error": (res.error or "")[:160], "sig": None,
                            "ex_set": None, "rows": 0, "ncols": 0, "ms": r["ms"]})
            continue
        m, s = ex.compare(res.rows, gold.rows)
        samples.append({"sql": sql, "guard": None, "exec": True, "sig": signature(res.rows),
                        "ex_set": s, "ex_multiset": m, "rows": len(res.rows),
                        "ncols": len(res.rows[0]) if res.rows else 0,
                        "ms": round(res.ms, 3)})
    out["usage"] = usage
    out["sample_ex"] = [s["ex_set"] for s in samples]
    out["sample_exec"] = [bool(s["exec"]) for s in samples]

    win_sig, support, idx = vote(samples)
    out["support"] = support
    out["sql_unanimous"] = len({ex.normalize_sql(s["sql"]) for s in samples if s["sql"]}) == 1
    if win_sig is None:
        out["status"] = "llm_failed"
        out["samples"] = [{k: s[k] for k in ("sql", "guard", "exec", "error", "ms") if k in s}
                          for s in samples]
        return out

    w = samples[idx]
    out["samples"] = [{k: s[k] for k in ("sql", "guard", "exec", "error", "sig", "ex_set", "rows", "ncols")
                       if k in s} for s in samples]
    out["winner"] = {"sql": w["sql"], "sig": w["sig"], "ex_set": w["ex_set"],
                     "rows": w["rows"], "ncols": w["ncols"]}
    out["status"] = "ok"
    # Validators need the actual rows. They are intentionally re-fetched from the
    # winning SQL rather than kept per sample: one read-only run at p50 ~2 ms is
    # cheaper than holding 2,500 result sets in memory.
    rows = ex.execute(db_path, w["sql"]).rows if w.get("sql") else []
    try:
        out["flags"] = V.validate(db_path, q["question"], w["sql"], rows)
    except Exception as e:  # noqa: BLE001 - a validator crash must not lose the sample
        out["flags"] = {"any": False, "error": str(e)[:120]}
    return out


def run(args):
    qfile = None
    import glob

    for f in glob.glob(os.path.join(args.data_dir, "**", "*.json"), recursive=True):
        if "mini_dev" in os.path.basename(f):
            qfile = f
            break
    if not qfile:
        raise SystemExit("no question file under %s" % args.data_dir)
    qs = json.load(open(qfile, encoding="utf-8"))
    if args.limit:
        qs = qs[: args.limit]
    db_dir = os.path.join(args.data_dir, "databases")
    if not os.path.isdir(db_dir):
        db_dir = args.data_dir

    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(solve_one, q, db_dir, args.schema_mode, args.data_dir,
                            args.samples, args.evidence) for q in qs]
        for i, f in enumerate(futs):
            try:
                rows.append(f.result())
            except Exception as e:  # noqa: BLE001
                rows.append({"id": qs[i]["question_id"], "status": "crashed", "error": str(e)[:200]})
            if (i + 1) % 25 == 0:
                print("  %d/%d  %.0fs" % (i + 1, len(qs), time.time() - t0), flush=True)

    price = H.PRICE
    usage = {k: sum(r.get("usage", {}).get(k, 0) for r in rows) for k in ("in", "out", "hit", "miss")}
    cost = (usage["miss"] * price["in_miss"] + usage["hit"] * price["in_hit"]
            + usage["out"] * price["out"]) / 1e6
    answered = [r for r in rows if r["status"] == "ok"]
    summary = {
        "dataset": "BIRD Mini-Dev (SQLite)",
        "n": len(rows),
        "samplesPerQuestion": args.samples,
        "schemaMode": args.schema_mode,
        "evidence": args.evidence,
        "model": H.MODEL,
        "ex_set": sum(1 for r in answered if r["winner"]["ex_set"]) / len(rows) if rows else 0.0,
        "sql_unanimous": sum(1 for r in answered if r["sql_unanimous"]),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "tokens": usage,
        "cost_usd": round(cost, 4),
        "wall_s": round(time.time() - t0, 1),
    }
    out = {"summary": summary, "rows": rows}
    path = args.out or os.path.join(HERE, "results.json")
    json.dump(out, open(path, "w"), ensure_ascii=False)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("wrote", path)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--schema-mode", default="samples")
    ap.add_argument("--evidence", default="off", choices=["on", "off"])
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        r = V.selftest()
        print(json.dumps({k: v for k, v in r.items() if k != "cases"}, ensure_ascii=False))
        for c in r["cases"]:
            if not c["pass"]:
                print("FAIL", c)
        raise SystemExit(0 if r["ok"] else 1)
    if not args.data_dir:
        raise SystemExit("--data-dir is required")
    run(args)


if __name__ == "__main__":
    main()
