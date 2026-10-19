#!/usr/bin/env python3
"""POC-74: the span contract must carry the signals we actually added.

POC-65/66/68 introduced `support`, structural `flags`, `routing` and repair
`stage`/`outcome`. None of them existed in `nl2charts.span.v1`. That is the
quiet form of contract drift: the product knows more than its telemetry, so
every question about "why did this answer go out unreviewed?" is unanswerable
from traces alone.

This POC extends the contract with two rules and validates them mechanically:

  1. extensions are OPTIONAL and typed — an old v1.0 span must still validate
     (API1 rule A4: new fields are optional), and a malformed new field must not
  2. every value is low-cardinality or numeric — no free text, no SQL, no rows

Seven mutations, one per failure mode, plus a positive control (the v1.0 span).

Usage: python3 poc/74/run.py [--out results.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# name -> (type, required, enum or None, min, max)
CORE = {
    "nl2charts.span.kind": ("str", True, {"ask", "intent", "generate", "guard", "execute", "chart", "repair"}, None, None),
    "nl2charts.model": ("str", True, None, None, None),
    "nl2charts.prompt.hash": ("str", True, None, None, None),
}
EXT = {
    "nl2charts.confidence.n": ("int", False, None, 1, 16),
    "nl2charts.confidence.support": ("int", False, None, 0, 16),
    "nl2charts.confidence.value": ("float", False, None, 0.0, 1.0),
    "nl2charts.routing": ("str", False, {"auto", "review"}, None, None),
    "nl2charts.flags": ("list", False, {"shape", "fanout", "literal", "degenerate"}, None, None),
    "nl2charts.repair.stage": ("int", False, None, 1, 2),
    "nl2charts.repair.signal": ("str", False, {"exec_error", "empty_result", "flag"}, None, None),
    "nl2charts.repair.outcome": ("str", False, {"fixed", "unfixed", "not_attempted"}, None, None),
}
ALL = {**CORE, **EXT}
LEAK = re.compile(r"\b(select|from|where|join)\b\s", re.I)


def _type_ok(value, kind):
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "list":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    return False


def validate(span: dict) -> list[dict]:
    v = []
    attrs = span.get("attrs") or {}
    for name, (kind, required, enum, lo, hi) in CORE.items():
        if name not in attrs:
            v.append({"rule": "required", "attr": name})
    for name, value in attrs.items():
        if name not in ALL:
            v.append({"rule": "unknown", "attr": name})
            continue
        kind, _req, enum, lo, hi = ALL[name]
        if not _type_ok(value, kind):
            v.append({"rule": "type", "attr": name, "value": type(value).__name__})
            continue
        if enum is not None:
            items = value if isinstance(value, list) else [value]
            for it in items:
                if it not in enum:
                    v.append({"rule": "enum", "attr": name, "value": it})
        if kind in ("int", "float"):
            if lo is not None and value < lo:
                v.append({"rule": "range", "attr": name, "value": value})
            if hi is not None and value > hi:
                v.append({"rule": "range", "attr": name, "value": value})
        if kind == "str" and LEAK.search(value):
            v.append({"rule": "content-text", "attr": name})
    # cross-field: support <= n, value == support/n when both present
    n = attrs.get("nl2charts.confidence.n")
    s = attrs.get("nl2charts.confidence.support")
    val = attrs.get("nl2charts.confidence.value")
    if isinstance(n, int) and isinstance(s, int):
        if s > n:
            v.append({"rule": "cross", "why": "support > n"})
        if isinstance(val, (int, float)) and n > 0 and abs(val - s / n) > 1e-6:
            v.append({"rule": "cross", "why": "value != support/n"})
    return v


def base_span(**attrs):
    a = {"nl2charts.span.kind": "ask", "nl2charts.model": "deepseek-chat",
         "nl2charts.prompt.hash": "sha256:9f2c"}
    a.update(attrs)
    return {"name": "nl2charts.ask", "schemaVersion": "nl2charts.span.v1", "attrs": a}


def cases():
    """One positive control plus one span per failure mode."""
    out = []
    out.append({"case": "v1.0 span (no extensions)", "span": base_span(), "want": 0})
    out.append({"case": "v1.1 auto route", "span": base_span(**{
        "nl2charts.confidence.n": 5, "nl2charts.confidence.support": 5,
        "nl2charts.confidence.value": 1.0, "nl2charts.routing": "auto",
        "nl2charts.flags": []}), "want": 0})
    out.append({"case": "v1.1 review with flags", "span": base_span(**{
        "nl2charts.confidence.n": 5, "nl2charts.confidence.support": 3,
        "nl2charts.confidence.value": 0.6, "nl2charts.routing": "review",
        "nl2charts.flags": ["literal", "shape"],
        "nl2charts.repair.stage": 2, "nl2charts.repair.signal": "flag",
        "nl2charts.repair.outcome": "fixed"}), "want": 0})
    out.append({"case": "M1 missing required", "span": {"name": "x", "attrs": {
        "nl2charts.model": "m", "nl2charts.prompt.hash": "h"}}, "want": 1})
    out.append({"case": "M2 wrong type", "span": base_span(**{
        "nl2charts.confidence.support": "5"}), "want": 1})
    out.append({"case": "M3 bad enum", "span": base_span(**{
        "nl2charts.routing": "maybe"}), "want": 1})
    out.append({"case": "M4 unknown attr", "span": base_span(**{
        "nl2charts.foo": 1}), "want": 1})
    out.append({"case": "M5 SQL text leaks", "span": base_span(**{
        "nl2charts.repair.signal": "SELECT 1"}), "want": 1})
    out.append({"case": "M6 support > n", "span": base_span(**{
        "nl2charts.confidence.n": 3, "nl2charts.confidence.support": 4}), "want": 1})
    out.append({"case": "M7 value != support/n", "span": base_span(**{
        "nl2charts.confidence.n": 5, "nl2charts.confidence.support": 2,
        "nl2charts.confidence.value": 0.9}), "want": 1})
    return out


def run():
    rows = []
    for c in cases():
        v = validate(c["span"])
        rows.append({"case": c["case"], "violations": v, "count": len(v),
                     "pass": (len(v) > 0) == (c["want"] > 0)})
    ok = all(r["pass"] for r in rows)
    return {"cases": rows, "pass": sum(1 for r in rows if r["pass"]),
            "total": len(rows), "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "results.json"))
    args = ap.parse_args()
    r = run()
    json.dump({"summary": {"cases": r["total"], "pass": r["pass"], "ok": r["ok"]},
               "rows": r["cases"]}, open(args.out, "w"), ensure_ascii=False)
    print(json.dumps({"pass": r["pass"], "total": r["total"], "ok": r["ok"]}, ensure_ascii=False))
    for row in r["cases"]:
        if not row["pass"]:
            print("FAIL", row["case"], row["violations"])
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
