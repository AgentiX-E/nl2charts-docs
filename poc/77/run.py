#!/usr/bin/env python3
"""POC-77: Spider2-Lite on the SQLite subset — the first benchmark where our
schemas are actually big.

Everything measured so far (BIRD Mini-Dev, nvBench) sits on small schemas: BIRD
Mini-Dev's 11 databases top out at 221 columns, and POC-63 found that schema
linking *hurts* there. That result has always carried a caveat — it may be an
artefact of small schemas. Spider2-Lite is the counter-case: 260 questions over
enterprise databases, and the subset that ships as SQLite has a median of 76
columns per database and a maximum of 352 across 26–38 tables.

So this is not another leaderboard attempt. It is the control experiment for
POC-63: if linking is useless here too, the negative result generalises; if it
matters here, the earlier conclusion was scoped to small schemas all along.

Data (neither file is vendored; both are fetched by URL/SHA):
  xlangai/spider2-lite          spider2-lite.jsonl   260 questions
  xlangai/spider2-localdb       sqlite.zip           80 databases, 2.4 GB unpacked
  xlang-ai/Spider2 (GitHub)     gold/exec_result/<id>_{a,b,c}.csv

A question passes if its result matches ANY published variant (the gold ships
a/b/c because several readings are legitimate — the same reason BIRD2 asks for
paired tests rather than a single number).

Usage:
  python3 poc/77/run.py --fetch            # download the 40 gold variants
  python3 poc/77/run.py --run              # evaluate
  python3 poc/77/run.py --selftest
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sqlite3
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import ex  # noqa: E402
import link as L  # noqa: E402
import run as H  # noqa: E402

RAW = "https://raw.githubusercontent.com/xlang-ai/Spider2/main/spider2-lite/evaluation_suite/gold/exec_result"
DATA = os.environ.get("SPIDER2_DATA", "/root/data/spider2")

SYS = ("You are a senior data analyst. Write ONE SQLite query that answers the "
       "question against the schema. Reply with the SQL only, no explanation, "
       "no markdown fence.")


def split_db(paths: dict, rows: list) -> list[dict]:
    return [r for r in rows if r["db"] in paths]


_SCHEMA_SIZE: dict[str, int] = {}


def schema_columns(db_path: str) -> int:
    """Columns in the database, not in the card. Measuring the card would make
    the linked arm look like it has smaller databases."""
    if db_path in _SCHEMA_SIZE:
        return _SCHEMA_SIZE[db_path]
    c = sqlite3.connect(db_path)
    n = 0
    for (t,) in c.execute("select name from sqlite_master where type='table'"):
        n += len(list(c.execute(f'PRAGMA table_info("{t}")')))
    c.close()
    _SCHEMA_SIZE[db_path] = n
    return n


def schema_card(db_path: str, max_cols: int = 0) -> str:
    c = sqlite3.connect(db_path)
    out = []
    for (t,) in c.execute("select name from sqlite_master where type='table' order by name"):
        cols = [f'{n} {ty}' for _, n, ty, *_ in c.execute(f'PRAGMA table_info("{t}")')]
        if max_cols:
            cols = cols[:max_cols]
        out.append(f"{t}({', '.join(cols)})")
    c.close()
    return "\n".join(out)


def coerce(s: str):
    """Gold CSVs are text; compare numbers as numbers so 4340.10 == 4340.1."""
    t = (s or "").strip()
    if t == "":
        return None
    try:
        if t.lstrip("-").isdigit():
            return int(t)
        return float(t)
    except ValueError:
        return t


def load_gold(path: str):
    with open(path, encoding="utf-8", errors="replace") as f:
        rd = csv.reader(f)
        rows = list(rd)
    if not rows:
        return []
    body = rows[1:] if rows else []
    return [tuple(coerce(x) for x in r) for r in body]


def match_any(pred, golds):
    for g in golds:
        if not g:
            continue
        m, _s = ex.compare(pred, g)
        if m:
            return True
    return False


def _pull(args):
    url, path = args
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        with urllib.request.urlopen(url, timeout=25) as resp:
            data = resp.read()
        if data:
            open(path, "wb").write(data)
            return True
    except Exception:
        pass
    return False


def fetch_gold(rows, gold_dir, workers=12):
    """One request per (instance, variant). Sequential fetching took ~43 s per
    file from this sandbox, so 120 files would be over an hour; the gold files
    are a few hundred bytes each and the endpoint is happy with 12 in flight."""
    os.makedirs(gold_dir, exist_ok=True)
    jobs, index = [], {}
    for r in rows:
        names = []
        for suf in ("a", "b", "c"):
            p = os.path.join(gold_dir, f"{r['instance_id']}_{suf}.csv")
            jobs.append((f"{RAW}/{r['instance_id']}_{suf}.csv", p))
            names.append(p)
        index[r["instance_id"]] = names
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_pull, jobs))
    return {k: [p for p in v if os.path.exists(p) and os.path.getsize(p) > 0]
            for k, v in index.items()}


def linked_card(db_path: str, question: str, k: int = 8) -> str:
    """Same selector POC-63 measured on BIRD, applied to the big schemas.

    POC-63 found linking cost -3.2pp on BIRD Mini-Dev, where the median database
    has 3-6 tables and nothing needs selecting. Here the median is 76 columns
    across 16 tables; if the negative result was really "small schemas", this is
    where it should flip.
    """
    stats = L.table_stats(db_path)
    picked, _info = L.select(stats, question, k=k)
    names = [p[0] if isinstance(p, tuple) else p for p in picked]
    c = sqlite3.connect(db_path)
    out = []
    for t in names:
        cols = [f"{n} {ty}" for _, n, ty, *_ in c.execute(f'PRAGMA table_info("{t}")')]
        if cols:
            out.append(f"{t}({', '.join(cols)})")
    c.close()
    return "\n".join(out)


def one(row, paths, gold, arm="full"):
    db = paths[row["db"]]
    card = schema_card(db, max_cols=0) if arm == "full" else linked_card(db, row["question"])
    q = row["question"]
    if row.get("external_knowledge"):
        q += "\n\n(Reference document: %s — not provided, answer from the schema alone.)" % row["external_knowledge"]
    r = H.call([{"role": "system", "content": SYS},
                {"role": "user", "content": "Schema:\n%s\n\nQuestion: %s" % (card, q)}])
    sql, _f = ex.strip_fence(r["text"])
    out = {"id": row["instance_id"], "db": row["db"], "arm": arm,
           "cardTables": card.count("("), "cardChars": len(card), "sql": sql[:800],
           "usage": r["usage"], "ncols": schema_columns(db)}
    try:
        res = ex.execute(db, sql)
        out["status"] = "ok" if res.ok else "sql_error"
        if not res.ok:
            out["error"] = (res.error or "")[:120]
        pred = [tuple(x) for x in res.rows][:5000]
        out["rows"] = len(pred)
        golds = [load_gold(p) for p in gold.get(row["instance_id"], [])]
        out["goldVariants"] = len(golds)
        out["ex"] = bool(golds) and match_any(pred, golds)
    except Exception as e:  # noqa: BLE001
        out["status"] = "error"
        out["error"] = str(e)[:120]
        out["ex"] = False
    return out


def summarise(rows, wall, cost, tokenc):
    n = len(rows)
    ok = sum(1 for r in rows if r.get("ex"))
    noGold = sum(1 for r in rows if not r.get("goldVariants"))
    by_size = {}
    for label, lo, hi in (("<=50 cols", 0, 50), (">50 cols", 51, 150), (">150 cols", 151, 10 ** 6)):
        g = [r for r in rows if lo <= (r.get("ncols") or 0) <= hi]
        if g:
            by_size[label] = {"n": len(g), "ex": round(sum(1 for r in g if r.get("ex")) / len(g), 4)}
    errs = [r for r in rows if r.get("status") == "sql_error"]
    return {"n": n, "ex": round(ok / n, 4) if n else None, "correct": ok,
            "sqlErrorRate": round(len(errs) / n, 4) if n else None,
            "avgCardChars": round(sum(r.get("cardChars") or 0 for r in rows) / n) if n else None,
            "noGold": noGold, "bySchemaSize": by_size,
            "statuses": dict(Counter(r.get("status") for r in rows)),
            "tokens": tokenc, "cost_usd": round(cost, 4), "wall_s": round(wall, 1),
            "model": H.MODEL}


def selftest() -> int:
    muts = []
    # coerce: gold text must become the same token class sqlite returns
    muts.append({"mutation": "coerce-int", "caught": coerce("42") == 42})
    muts.append({"mutation": "coerce-float", "caught": coerce("4340.1019") == 4340.1019})
    muts.append({"mutation": "coerce-empty-null", "caught": coerce("  ") is None})
    muts.append({"mutation": "coerce-text", "caught": coerce("Afghanistan") == "Afghanistan"})
    # compare: rounded floats match, order does not matter
    muts.append({"mutation": "compare-float-round", "caught":
                 ex.compare([(4340.10190001,)], [(4340.1019,)])[0]})
    muts.append({"mutation": "compare-order", "caught":
                 ex.compare([(1, "a"), (2, "b")], [("b", 2), ("a", 1)])[0] is False})
    muts.append({"mutation": "compare-count", "caught":
                 ex.compare([(1,), (1,)], [(1,)])[0] is False})
    # match_any: a question may be right under a different legitimate reading
    muts.append({"mutation": "match-any-second-variant", "caught":
                 match_any([(3,)], [[(1,)], [(3,)]])})
    muts.append({"mutation": "match-any-none", "caught":
                 not match_any([(9,)], [[(1,)], [(3,)]])})
    # an empty gold must never count as a pass
    muts.append({"mutation": "empty-gold-not-pass", "caught": not match_any([(1,)], [[]])})
    ok = all(m["caught"] for m in muts)
    print(json.dumps({"selftest": muts, "ok": ok}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--arm", default="full", choices=["full", "linked"])
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    import glob
    paths = {os.path.basename(p)[:-7]: p for p in glob.glob(os.path.join(args.data, "db", "**", "*.sqlite"), recursive=True)}
    rows = [json.loads(l) for l in open(os.path.join(args.data, "spider2-lite.jsonl"), encoding="utf-8")]
    sub = split_db(paths, rows)
    if args.limit:
        sub = sub[:args.limit]
    gold_dir = "/tmp/spider2_gold"

    if args.fetch:
        got = fetch_gold(sub, gold_dir)
        have = sum(1 for v in got.values() if v)
        print(json.dumps({"instances": len(sub), "withGold": have,
                          "goldDir": gold_dir}, ensure_ascii=False))
        return 0

    if not args.run:
        print(json.dumps({"instances": len(sub), "dbs": len({r["db"] for r in sub}),
                          "note": "use --fetch then --run"}, ensure_ascii=False))
        return 0

    got = fetch_gold(sub, gold_dir)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        out = list(pool.map(lambda r: one(r, paths, got, args.arm), sub))
    tokenc = Counter()
    for r in out:
        for k, v in (r.get("usage") or {}).items():
            tokenc[k] += v or 0
    cost = (tokenc["miss"] * H.PRICE["in_miss"] + tokenc["hit"] * H.PRICE["in_hit"]
            + tokenc["out"] * H.PRICE["out"]) / 1e6
    summary = summarise(out, time.time() - t0, cost, dict(tokenc))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.out:
        json.dump({"summary": summary, "rows": out}, open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
