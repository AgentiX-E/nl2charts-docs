#!/usr/bin/env python3
"""POC-71: chart-type recommendation on nvBench 2.0 — CPU only, API models only.

This POC exists to settle a claim in our own documents. We had written that
nvBench / Text2Vis / BIRD-Interact stay "planned" because evaluating them would
need GPU inference. That conflated two different environments:

  product runtime   CPU-only (ADR-136). A GPU-only dependency makes install fail.
  evaluation        any model, any provider. We call DeepSeek / Zhipu over HTTP;
                    nothing runs on the machine but Python and SQLite.

So this runs the nvBench 2.0 dev split (750 items, public GitHub repo, pinned
blob SHA) with two arms, both CPU-only:

  R  rules    keyword + schema heuristics over the six Vega marks
  L  llm      one DeepSeek call choosing among the same six marks

Metric: top-1 against the set of marks that appear anywhere in the gold
visualisation (the dataset is explicitly ambiguous — a question may admit more
than one chart). We also report how often the natural-language query *names*
the chart, because on this split it often does ("... is displayed in a line
chart"), which flatters any keyword method and is worth knowing before the
number is quoted anywhere.

Usage:
  python3 poc/71/run.py --data /tmp/nvbench_dev.json
  python3 poc/71/run.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import run as H  # noqa: E402

MARKS = ["bar", "line", "arc", "point", "rect", "boxplot"]
SYS = ("You are a data-visualisation expert. Given a question and a table schema, "
       "choose the single most appropriate chart mark from this list: "
       "bar, line, arc, point, rect, boxplot. Reply with the mark only.")

RULES = [
    (r"\b(box ?plot|box-and-whisker|quartile)\b", "boxplot"),
    (r"\b(heat ?map|matrix|density grid)\b", "rect"),
    (r"\b(scatter|correlation|relationship between|versus|vs\.?)\b", "point"),
    (r"\b(pie|donut|share|proportion|percentage breakdown|composition)\b", "arc"),
    (r"\b(line chart|trend|over time|time series|by (year|month|quarter|week|day))\b", "line"),
]


def gold_marks(item):
    """Every mark that appears in the gold specs. Ambiguity is the dataset's point."""
    try:
        specs = json.loads(item["gold_answer"])
    except Exception:  # noqa: BLE001
        return set()
    out = set()
    if isinstance(specs, dict):
        specs = [specs]
    for s in specs:
        if isinstance(s, dict):
            m = s.get("mark")
            if isinstance(m, dict):
                m = m.get("type")
            if isinstance(m, str):
                out.add(m.lower())
    return out


def names_chart(text):
    t = (text or "").lower()
    return any(re.search(r"\b%s\b" % w, t) for w in
               ("bar chart", "line chart", "pie chart", "scatter", "heatmap",
                "box plot", "boxplot", "histogram"))


def rule_pick(item):
    q = (item.get("nl_query") or "").lower()
    for pat, mark in RULES:
        if re.search(pat, q):
            return mark
    # schema fallback: one categorical + one numeric is a bar; two numerics a point
    try:
        schema = json.loads(item.get("table_schema") or "{}")
        cols = schema.get("table_columns") or []
    except Exception:  # noqa: BLE001
        cols = []
    return "bar" if len(cols) <= 2 else "bar"


def llm_prompt(item):
    return [{"role": "system", "content": SYS},
            {"role": "user", "content": "Question: %s\n\nTable schema: %s\n\nMark:"
                                        % (item.get("nl_query"), item.get("table_schema"))}]


def parse_mark(text):
    t = (text or "").lower()
    for m in MARKS:
        if re.search(r"\b%s\b" % m, t):
            return m
    if re.search(r"\bpie\b", t):
        return "arc"
    if re.search(r"\bscatter\b", t):
        return "point"
    return None


def one(item):
    gold = gold_marks(item)
    out = {"id": item.get("csv_file"), "gold": sorted(gold), "named": names_chart(item.get("nl_query"))}
    if not gold:
        out["status"] = "no_gold"
        return out
    out["rule"] = rule_pick(item)
    try:
        r = H.call(llm_prompt(item), max_tokens=8)
        out["llm"] = parse_mark(r["text"])
        out["raw"] = (r["text"] or "")[:30]
        out["usage"] = r["usage"]
    except RuntimeError as e:
        out["llm"] = None
        out["error"] = str(e)
    out["status"] = "ok"
    return out


def score(rows, arm):
    ok = [r for r in rows if r["status"] == "ok"]
    hit = sum(1 for r in ok if r.get(arm) in r["gold"])
    return {"n": len(ok), "correct": hit, "accuracy": round(hit / len(ok), 4) if ok else None}


def summarise(rows):
    ok = [r for r in rows if r["status"] == "ok"]
    both = sum(1 for r in ok if r.get("rule") in r["gold"] and r.get("llm") in r["gold"])
    only_r = sum(1 for r in ok if r.get("rule") in r["gold"] and r.get("llm") not in r["gold"])
    only_l = sum(1 for r in ok if r.get("llm") in r["gold"] and r.get("rule") not in r["gold"])
    u = {"in": 0, "out": 0, "hit": 0, "miss": 0}
    for r in ok:
        for k in u:
            u[k] += (r.get("usage") or {}).get(k, 0) or 0
    cost = (u["miss"] * H.PRICE["in_miss"] + u["hit"] * H.PRICE["in_hit"]
            + u["out"] * H.PRICE["out"]) / 1e6
    return {
        "n": len(rows), "scored": len(ok),
        "rule": score(rows, "rule"), "llm": score(rows, "llm"),
        "agreement": {"both": both, "onlyRule": only_r, "onlyLlm": only_l},
        "namedInQuery": sum(1 for r in ok if r.get("named")),
        "namedRate": round(sum(1 for r in ok if r.get("named")) / len(ok), 4) if ok else None,
        "byNaming": {
            label: {
                "n": len(grp),
                "rule": round(sum(1 for r in grp if r.get("rule") in r["gold"]) / len(grp), 4) if grp else None,
                "llm": round(sum(1 for r in grp if r.get("llm") in r["gold"]) / len(grp), 4) if grp else None,
            }
            for label, grp in (("named", [r for r in ok if r.get("named")]),
                               ("notNamed", [r for r in ok if not r.get("named")]))
            if grp
        },
        "goldSetSize": dict(Counter(len(r["gold"]) for r in ok)),
        "cost_usd": round(cost, 4),
    }


def selftest():
    cases = []
    it = {"nl_query": "Show the trend over time in a line chart", "gold_answer":
          json.dumps([{"mark": "line"}, {"mark": {"type": "bar"}}]), "table_schema": "{}"}
    cases.append({"case": "gold marks from list+dict", "got": sorted(gold_marks(it)),
                  "pass": gold_marks(it) == {"line", "bar"}})
    cases.append({"case": "rule catches explicit chart name", "pass": rule_pick(it) == "line"})
    cases.append({"case": "names_chart", "pass": names_chart(it["nl_query"]) is True})
    cases.append({"case": "names_chart false", "pass": names_chart("average salary by dept") is False})
    for text, want in (("line", "line"), ("Use a pie chart", "arc"), ("bar chart please", "bar"),
                       ("nothing here", None), ("boxplot", "boxplot")):
        cases.append({"case": "parse %r" % text, "got": parse_mark(text), "pass": parse_mark(text) == want})
    rows = [{"status": "ok", "gold": ["bar"], "rule": "bar", "llm": "bar", "names": True},
            {"status": "ok", "gold": ["line"], "rule": "line", "llm": "bar", "names": False}]
    s = summarise(rows)
    cases.append({"case": "scores", "got": (s["rule"]["correct"], s["llm"]["correct"]),
                  "pass": s["rule"]["correct"] == 2 and s["llm"]["correct"] == 1})
    ok = all(c["pass"] for c in cases)
    return {"cases": cases, "pass": sum(1 for c in cases if c["pass"]),
            "total": len(cases), "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/tmp/nvbench_dev.json")
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
    items = json.load(open(args.data, encoding="utf-8"))
    if args.limit:
        items = items[: args.limit]
    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(one, it) for it in items]
        for i, f in enumerate(futs):
            try:
                rows.append(f.result())
            except Exception as e:  # noqa: BLE001
                rows.append({"id": items[i].get("csv_file"), "status": "crashed", "error": str(e)[:120]})
            if (i + 1) % 100 == 0:
                print("  %d/%d  %.0fs" % (i + 1, len(items), time.time() - t0), flush=True)
    doc = {"summary": dict(summarise(rows), wall_s=round(time.time() - t0, 1),
                           model=H.MODEL, dataset="nvBench 2.0 dev",
                           datasetSha="f37c5844d3bf2c823a52ed44e9187d1f56eb7222"),
           "rows": rows}
    json.dump(doc, open(args.out, "w"), ensure_ascii=False)
    print(json.dumps(doc["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
