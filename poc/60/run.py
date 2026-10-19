#!/usr/bin/env python3
"""POC-60: does the self-built Text-to-SQL path actually clear a public benchmark?

The whitepaper claimed a BIRD target without ever running BIRD. This script runs
the real thing: BIRD Mini-Dev (SQLite split), N samples per question, majority
vote, execution match against gold, with per-difficulty breakdown and cost.

Two schema modes are supported because the difference is a product decision, not
a taste: `names` is the minimum a metadata-only integration can offer, `samples`
adds three distinct values per text column. POC-8 measured the effect of sample
values on *linking*; this measures it on *generation*.

Usage:
  python3 run.py --data-dir ~/data/bird_mini_dev --limit 50
  python3 run.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ex  # noqa: E402
import metadata  # noqa: E402
import link  # noqa: E402

# DeepSeek list price, USD per million tokens (2026-10). Cache-hit input is
# billed at 1/10 of a miss (POC-53), so cost is reported both ways.
PRICE = {"in_miss": 0.27, "in_hit": 0.027, "out": 1.10}

API = "https://api.deepseek.com/chat/completions"
MODEL = os.environ.get("POC60_MODEL", "deepseek-chat")
K_TABLES = int(os.environ.get("POC63_K", "4"))


# ---------------------------------------------------------------- data


def find_db(db_dir: str, db_id: str) -> str | None:
    """Locate one database file.

    The upstream layout is not ours to choose and it changes: BIRD ships
    `databases/database/<db_id>/<db_id>_template.sqlite` in one repo and a flat
    `<db_id>.sqlite` in another. Matching on a prefix is the only rule that
    survives both, and it is still unambiguous because `db_id` is a full name.
    """
    import glob

    preferred = [
        os.path.join(db_dir, db_id, f"{db_id}.sqlite"),
        os.path.join(db_dir, db_id, "sqlite", f"{db_id}.sqlite"),
        os.path.join(db_dir, f"{db_id}.sqlite"),
        os.path.join(db_dir, db_id, f"{db_id}_template.sqlite"),
    ]
    for cand in preferred:
        if os.path.exists(cand):
            return cand
    hits = sorted(glob.glob(os.path.join(db_dir, "**", f"{db_id}*.sqlite"), recursive=True))
    if hits:
        # prefer an exact stem over a prefixed sibling (region vs region_2)
        exact = [h for h in hits if os.path.basename(h) in (f"{db_id}.sqlite", f"{db_id}_template.sqlite")]
        return (exact or hits)[0]
    return None


DESC_CACHE: dict[str, dict[str, str]] = {}
DESC_INDEX: dict[str, str] = {}


def index_descriptions(data_dir: str) -> dict[str, str]:
    """Map db_id -> description CSV path.

    BIRD ships column descriptions as `database_description/<db_id>.csv` with
    headers `original_column_name,column_name,column_description,...`. They are
    the only source of domain meaning ("is_active" means what?), and POC-60
    measures them as the largest single lever, so they are indexed explicitly
    rather than hoped for.
    """
    import glob

    if DESC_INDEX:
        return DESC_INDEX
    for f in glob.glob(os.path.join(data_dir, "**", "database_description", "*.csv"), recursive=True):
        DESC_INDEX[os.path.splitext(os.path.basename(f))[0]] = f
    return DESC_INDEX


def load_descriptions(db_id: str, data_dir: str) -> dict[str, str]:
    if db_id in DESC_CACHE:
        return DESC_CACHE[db_id]
    import csv

    path = index_descriptions(data_dir).get(db_id)
    out: dict[str, str] = {}
    if path:
        try:
            with open(path, encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    name = (row.get("column_name") or row.get("original_column_name") or "").strip()
                    text = " ".join(
                        x.strip() for x in (row.get("column_description") or "", row.get("value_description") or "") if x
                    ).strip()
                    if name and text:
                        out[name.lower()] = text[:180]
        except Exception:  # noqa: BLE001 - a broken CSV must not stop the run
            out = {}
    DESC_CACHE[db_id] = out
    return out


SCHEMA_CACHE: dict[str, str] = {}


def schema_card(db_path: str, db_id: str, mode: str, data_dir: str = "", question: str = "") -> str:
    key = f"{db_path}|{mode}|{data_dir}"
    if key in SCHEMA_CACHE:
        return SCHEMA_CACHE[key]
    import sqlite3

    only_tables = None
    if mode == "link_lex":
        stats = link.table_stats(db_path)
        only_tables, _scores = link.select(stats, question, k=K_TABLES, with_fk=True)
        # Same format as `samples`, restricted to the selected tables. Changing
        # pruning AND formatting at once would confound the ablation -- the exact
        # mistake POC-61 taught us to avoid.
        mode = "samples"
        key = f"{db_path}|samples|{data_dir}|{'|'.join(sorted(only_tables))}"
        if key in SCHEMA_CACHE:
            return SCHEMA_CACHE[key]

    if mode in ("profile", "profile_lite"):
        info = metadata.profile(
            db_path,
            with_enums=(mode == "profile"),
            with_ranges=(mode == "profile"),
            with_keys=True,
        )
        card = metadata.render(info, db_id, with_enums=(mode == "profile"),
                               with_ranges=(mode == "profile"), with_keys=True)
        SCHEMA_CACHE[key] = card
        return card

    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    lines = [f"Database: {db_id}", ""]
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for t in tables:
            if only_tables is not None and t not in only_tables:
                continue
            cols = list(conn.execute(f'PRAGMA table_info("{t}")'))
            lines.append(f"Table: {t}")
            descs = load_descriptions(db_id, data_dir) if mode in ("desc", "full") else {}
            for _cid, name, ctype, _notnull, _default, pk in cols:
                suffix = " PRIVATE KEY" if pk else ""
                note = descs.get(name.lower())
                tail = f"  -- {note}" if note else ""
                lines.append(f"  {name} {ctype or 'TEXT'}{suffix}{tail}")
            if mode in ("samples", "full") and cols:
                sel = ", ".join(f'"{c[1]}"' for c in cols[:6])
                try:
                    rows = list(conn.execute(f'SELECT {sel} FROM "{t}" LIMIT 20'))
                    for i, c in enumerate(cols[:6]):
                        vals = []
                        for r in rows:
                            v = r[i]
                            if v is None:
                                continue
                            s = str(v)
                            if s not in vals:
                                vals.append(s)
                            if len(vals) == 3:
                                break
                        if vals:
                            lines.append(f"    -- {c[1]} e.g. {', '.join(vals)}")
                except Exception:  # noqa: BLE001 - sample values are a nicety
                    pass
    finally:
        conn.close()
    card = "\n".join(lines)
    SCHEMA_CACHE[key] = card
    return card


# ---------------------------------------------------------------- model


def build_prompt(q, card: str, evidence: str) -> list[dict]:
    sys_p = (
        "You are a text-to-SQL engine. Given a SQLite schema and a question, "
        "output exactly one SQL statement and nothing else."
    )
    user = [card, ""]
    ev = (q.get("evidence") or "").strip()
    if evidence == "on" and ev:
        user.append(f"Hint: {ev}")
    user.append(f"Question: {q['question']}")
    user.append("SQL:")
    return [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": "\n".join(user)},
    ]


def call(messages, max_tokens=400, temperature=0.0, tries=5):
    body = json.dumps(
        {
            "model": MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode()
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY")
    last = None
    for i in range(tries):
        req = urllib.request.Request(
            API,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.load(r)
            ms = (time.perf_counter() - t0) * 1000
            msg = d["choices"][0]["message"]["content"]
            u = d.get("usage", {})
            return {
                "text": msg,
                "ms": ms,
                "usage": {
                    "in": u.get("prompt_tokens", 0),
                    "out": u.get("completion_tokens", 0),
                    "hit": u.get("prompt_cache_hit_tokens", 0),
                    "miss": u.get("prompt_cache_miss_tokens", u.get("prompt_tokens", 0)),
                },
                "model": d.get("model"),
            }
        except urllib.error.HTTPError as e:
            code = e.code
            last = f"LLM_HTTP_{code}"
            if code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(1.5 * (i + 1))
                continue
            raise RuntimeError(last)
        except Exception as e:  # noqa: BLE001
            last = f"LLM_NET_{type(e).__name__}"
            if i < tries - 1:
                time.sleep(1.5 * (i + 1))
                continue
            raise RuntimeError(last)
    raise RuntimeError(last or "LLM_UNKNOWN")


# ---------------------------------------------------------------- one question


def run_question(q, db_dir, samples, mode, evidence, data_dir=""):
    db_path = find_db(db_dir, q["db_id"])
    out = {"id": q["question_id"], "db_id": q["db_id"],
           "difficulty": (q.get("difficulty") or "unknown").lower()}
    if not db_path:
        out.update(status="db_missing")
        return out

    gold = ex.execute(db_path, q["SQL"])
    out["gold_ok"] = gold.ok
    if not gold.ok:
        out.update(status="gold_error", gold_error=gold.error)
        return out
    out["gold_ms"] = round(gold.ms, 3)

    card = schema_card(db_path, q["db_id"], mode, data_dir, q["question"])
    out["cardChars"] = len(card)
    if mode == "link_lex":
        stats = link.table_stats(db_path)
        out["pickedTables"], _ = link.select(stats, q["question"], k=K_TABLES, with_fk=True)
    msgs = build_prompt(q, card, evidence)

    got = []
    for _ in range(samples):
        try:
            r = call(msgs)
        except RuntimeError as e:
            got.append({"sql": "", "ok": False, "err": str(e), "ms": 0, "usage": {}})
            continue
        sql, fenced = ex.strip_fence(r["text"])
        got.append({"sql": sql, "ok": True, "fenced": fenced, "ms": r["ms"],
                    "usage": r["usage"], "model": r["model"]})

    usable = [g for g in got if g["ok"]]
    out["samples"] = len(got)
    out["fenced"] = sum(1 for g in got if g.get("fenced"))
    out["llm_errors"] = len(got) - len(usable)
    out["usage"] = {
        "in": sum(g["usage"].get("in", 0) for g in usable),
        "out": sum(g["usage"].get("out", 0) for g in usable),
        "hit": sum(g["usage"].get("hit", 0) or 0 for g in usable),
        "miss": sum(g["usage"].get("miss", 0) or 0 for g in usable),
    }
    if not usable:
        out.update(status="llm_failed")
        return out

    # per-sample correctness, so pass@1 and majority@k are separable
    per = []
    for g in usable:
        allowed, why = ex.guard(g["sql"])
        if not allowed:
            per.append({"guard": why})
            continue
        r = ex.execute(db_path, g["sql"])
        if not r.ok:
            per.append({"exec_error": r.error})
            continue
        m, s = ex.compare(r.rows, gold.rows)
        per.append({"multiset": m, "set": s, "ms": r.ms, "cols": ex.column_count(r.rows)})
    # pass@1 = the FIRST sample is correct (standard definition); sample
    # accuracy = fraction of all samples correct. Conflating them hides whether
    # a gain came from voting or from a better prompt.
    out["pass_at_1_set"] = 1.0 if per[0].get("set") else 0.0
    out["sample_accuracy"] = sum(1 for p in per if p.get("set")) / len(per)
    out["guard_rejects"] = sum(1 for p in per if p.get("guard"))
    out["exec_errors"] = sum(1 for p in per if p.get("exec_error"))

    pick = ex.majority([(g["sql"], True) for g in usable])
    out["vote"] = ex.vote_stats([(g["sql"], True) for g in usable])
    out["sql"] = pick

    allowed, why = ex.guard(pick)
    if not allowed:
        out.update(status="guarded", guard=why)
        return out
    r = ex.execute(db_path, pick)
    if not r.ok:
        out.update(status="exec_error", exec_error=r.error)
        return out
    m, s = ex.compare(r.rows, gold.rows)
    out.update(status="ok", ex_multiset=m, ex_set=s, pred_ms=round(r.ms, 3),
               rows=len(r.rows), gold_rows=len(gold.rows))
    return out


def probe(data_dir, db_dir, limit=0):
    """Print what the cache actually contains. Cheap, and it settles arguments."""
    import glob
    import sqlite3

    files = sorted(glob.glob(os.path.join(db_dir, "**", "*.sqlite"), recursive=True))
    out = {"dbFiles": len(files), "totalBytes": sum(os.path.getsize(f) for f in files), "dbs": []}
    for f in files:
        entry = {"file": os.path.relpath(f, db_dir), "bytes": os.path.getsize(f)}
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % f, uri=True)
            tabs = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            entry["tables"] = len(tabs)
            entry["rows"] = {
                t: conn.execute('SELECT count(*) FROM "%s"' % t).fetchone()[0] for t in tabs[:3]
            }
            conn.close()
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)[:80]
        out["dbs"].append(entry)
    out["emptyDbs"] = sum(1 for d in out["dbs"] if sum(d.get("rows", {}).values()) == 0)
    # one real card, so a bad prompt is visible in the CI log instead of being
    # inferred from a score
    if files:
        first = files[0]
        db_id = os.path.basename(os.path.dirname(first)) or os.path.basename(first).split(".")[0]
        info = metadata.profile(first)
        card = metadata.render(info, db_id)
        fks = sum(1 for t in info.values() for c in t["cols"] if c.get("fk"))
        out["cardSample"] = {"dbId": db_id, "chars": len(card), "fks": fks,
                             "tables": len(info), "text": card[:1800]}
    return out


# ---------------------------------------------------------------- selftest


def selftest():
    """Mutation tests for the comparator. A comparator that cannot fail is a
    comparator that proves nothing, so each mutation targets one rule."""
    import sqlite3
    import tempfile

    tmp = tempfile.mkdtemp(prefix="poc60-")
    db = os.path.join(tmp, "t.sqlite")
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE t(a INT, b TEXT);"
        "INSERT INTO t VALUES (1,'x'),(1,'x'),(2,'y'),(3.00001,'z');"
    )
    c.commit()
    c.close()

    res = []
    gold = ex.execute(db, "SELECT a, b FROM t").rows

    def case(name, pred_sql, expect, gold_rows=None):
        r = ex.execute(db, pred_sql)
        m, s = ex.compare(r.rows, gold_rows if gold_rows is not None else gold)
        res.append({"case": name, "multiset": m, "set": s,
                    "expected": expect, "pass": (m, s) == expect})

    case("identical", "SELECT a, b FROM t", (True, True))
    case("row order differs", "SELECT a, b FROM t ORDER BY b DESC", (True, True))
    case("duplicate collapsed", "SELECT DISTINCT a, b FROM t", (False, True))
    case("value changed", "SELECT a+10, b FROM t", (False, False))
    case("float rounded", "SELECT round(a,4), b FROM t", (True, True))
    case("column count differs", "SELECT a FROM t", (False, False))

    # guard mutations
    g = []
    for sql, ok in [
        ("SELECT 1", True),
        ("  with x as (select 1) select * from x", True),
        ("DELETE FROM t", False),
        ("WITH x AS (DELETE FROM t RETURNING a) SELECT * FROM x", False),
        ("SELECT 1; DROP TABLE t", False),
        ("PRAGMA writable_schema=1", False),
        ("-- comment only", False),
    ]:
        allowed, _why = ex.guard(sql)
        g.append({"sql": sql, "allowed": allowed, "expected": ok, "pass": allowed == ok})

    # fence mutations
    f = []
    for raw, want_sql, want_fence in [
        ("```sql\nSELECT 1\n```", "SELECT 1", True),
        ("```\nSELECT 1\n```", "SELECT 1", True),
        ("SELECT 1", "SELECT 1", False),
    ]:
        s, fenced = ex.strip_fence(raw)
        f.append({"input": raw[:20], "sql": s, "fenced": fenced,
                  "pass": s == want_sql and fenced == want_fence})

    # vote mutations
    v = []
    a = [("SELECT 1", True), ("SELECT 1 ", True), ("SELECT 2", True)]
    v.append({"case": "2 of 3 agree", "pick": ex.majority(a), "pass": ex.majority(a) == "SELECT 1"})
    b = [("SELECT 2", True), ("SELECT 1", True), ("SELECT 1 ", True)]
    v.append({"case": "order does not matter", "pick": ex.majority(b), "pass": ex.majority(b) == "SELECT 1"})

    ok = all(x["pass"] for x in res + g + f + v)
    return {"comparator": res, "guard": g, "fence": f, "vote": v,
            "pass": sum(1 for x in res + g + f + v if x["pass"]),
            "total": len(res + g + f + v), "ok": ok}


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.expanduser("~/data/bird_mini_dev"))
    ap.add_argument("--questions", default=None)
    ap.add_argument("--db-dir", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--schema-mode",
                    choices=["names", "samples", "desc", "full", "profile", "profile_lite", "link_lex"],
                    default="profile")
    ap.add_argument("--evidence", choices=["on", "off"], default="off")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(HERE, "results.json"))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        r = selftest()
        m = metadata.selftest()
        r["metadata"] = m
        r["pass"] += m["pass"]
        r["total"] += m["total"]
        r["ok"] = r["ok"] and m["ok"]
        lk = link.selftest()
        r["link"] = lk
        r["pass"] += lk["pass"]
        r["total"] += lk["total"]
        r["ok"] = r["ok"] and lk["ok"]
        print(json.dumps({"selftest": {"pass": r["pass"], "total": r["total"], "ok": r["ok"]}},
                         ensure_ascii=False))
        json.dump(r, open(os.path.join(HERE, "selftest.json"), "w"), indent=1)
        return 0 if r["ok"] else 1

    if a.probe:
        r = probe(a.data_dir, a.db_dir or os.path.join(a.data_dir, "databases"))
        print(json.dumps(r, ensure_ascii=False, indent=1)[:4000])
        return 0 if r["emptyDbs"] == 0 else 1

    if not (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY")):
        print("DEEPSEEK_API_KEY is not set", file=sys.stderr)
        return 2

    qfile = a.questions or os.path.join(a.data_dir, "data",
                                        "mini_dev_sqlite-00000-of-00001.json")
    if not os.path.exists(qfile):
        for root, _d, files in os.walk(a.data_dir):
            for f in files:
                if f.endswith(".json") and "mini_dev" in f:
                    qfile = os.path.join(root, f)
                    break
    qs = json.load(open(qfile, encoding="utf-8"))
    if a.limit and a.limit < len(qs):
        random.Random(a.seed).shuffle(qs)
        qs = qs[: a.limit]
        qs.sort(key=lambda x: x["question_id"])

    db_dir = a.db_dir or os.path.join(a.data_dir, "databases")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        rows = list(pool.map(lambda q: run_question(q, db_dir, a.samples, a.schema_mode, a.evidence, a.data_dir), qs))
    wall = time.time() - t0

    ok = [r for r in rows if r.get("status") == "ok"]
    n = len(rows)
    ex_set = sum(1 for r in ok if r["ex_set"]) / n if n else 0
    ex_multi = sum(1 for r in ok if r["ex_multiset"]) / n if n else 0
    pass1 = sum(r.get("pass_at_1_set", 0) for r in rows) / n if n else 0
    sample_acc = sum(r.get("sample_accuracy", 0) for r in rows) / n if n else 0

    by_diff = {}
    for r in rows:
        d = r.get("difficulty", "unknown")
        b = by_diff.setdefault(d, {"n": 0, "set": 0})
        b["n"] += 1
        b["set"] += 1 if (r.get("status") == "ok" and r["ex_set"]) else 0
    for d, b in by_diff.items():
        b["ex_set"] = round(b["set"] / b["n"], 4) if b["n"] else 0.0

    tok = {"in": sum(r.get("usage", {}).get("in", 0) for r in rows),
           "out": sum(r.get("usage", {}).get("out", 0) for r in rows),
           "hit": sum(r.get("usage", {}).get("hit", 0) or 0 for r in rows),
           "miss": sum(r.get("usage", {}).get("miss", 0) or 0 for r in rows)}
    cost = (tok["miss"] * PRICE["in_miss"] + tok["hit"] * PRICE["in_hit"]
            + tok["out"] * PRICE["out"]) / 1e6

    lat = sorted(r["gold_ms"] for r in rows if "gold_ms" in r)
    summary = {
        "dataset": "BIRD Mini-Dev (SQLite)",
        "n": n,
        "samplesPerQuestion": a.samples,
        "schemaMode": a.schema_mode,
        "evidence": a.evidence,
        "model": MODEL,
        "ex_set": round(ex_set, 4),
        "ex_multiset": round(ex_multi, 4),
        "pass_at_1": round(pass1, 4),
        "sample_accuracy": round(sample_acc, 4),
        "vote_gain_pp": round((ex_set - pass1) * 100, 2),
        "byDifficulty": by_diff,
        "statuses": {s: sum(1 for r in rows if r.get("status") == s)
                     for s in sorted({r.get("status") for r in rows})},
        "fenced_outputs": sum(r.get("fenced", 0) for r in rows),
        "guard_rejects": sum(r.get("guard_rejects", 0) for r in rows),
        "exec_errors": sum(r.get("exec_errors", 0) for r in rows),
        "llm_errors": sum(r.get("llm_errors", 0) for r in rows),
        "unanimous": sum(1 for r in rows if r.get("vote", {}).get("unanimous")),
        "tokens": tok,
        "cost_usd": round(cost, 4),
        "wall_s": round(wall, 1),
        "gold_p50_ms": round(lat[len(lat) // 2], 2) if lat else None,
        "cardCharsP50": sorted(r.get("cardChars", 0) for r in rows)[len(rows) // 2],
        "descriptionIndex": len(index_descriptions(a.data_dir)),
        "descCoverage": round(
            sum(1 for q in qs if load_descriptions(q["db_id"], a.data_dir)) / max(1, len(qs)), 4),
    }
    json.dump({"summary": summary, "rows": rows}, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
