#!/usr/bin/env python3
"""POC-80: can a static guard turn silent divergence into a loud refusal?

POC-79 found that 3.8% of comparable questions produce the same statement
succeeding on two engines with different numbers. The design answer was
"unknown constructs must error, not drift" (ADR-151), but that was an assertion.
This module is the assertion turned into a checker, so it can be scored.

A guard that flags everything is useless, and a guard that flags nothing is
decoration. The only way to know which one this is: run it over the same 140
questions and count, against the divergences POC-79 actually observed,

  true positive   flagged, and the engines really disagreed
  false positive  flagged, but the engines agreed (this is the cost: a correct
                  query is refused)
  false negative  not flagged, and the engines disagreed (this is the failure
                  that reaches the user)

The rules are deliberately syntactic. A semantic checker would need to know the
data; the whole point of a guard is to run before execution.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# Each rule: (name, regex, why it diverges, severity)
# severity "hard" = refuse; "warn" = annotate and execute.
RULES = [
    ("substr-negative",
     re.compile(r"\b(substr|substring)\s*\(\s*[^,()]+,\s*-\s*\d", re.I),
     "SQLite counts from the end for a negative start; PostgreSQL clamps to 1", "hard"),
    ("round-double",
     re.compile(r"\bround\s*\(\s*(cast\s*\([^()]*\bas\s+(real|float|double)[^()]*\)|[^,()]*\bavg\s*\()", re.I),
     "PostgreSQL has no round(double precision, int); SQLite rounds anything", "hard"),
    ("backtick-ident",
     re.compile(r"`"),
     "SQLite accepts backtick-quoted identifiers; PostgreSQL does not", "hard"),
    ("iif",
     re.compile(r"\biif\s*\(", re.I),
     "SQLite's three-argument IIF has no PostgreSQL equivalent", "hard"),
    ("julianday",
     re.compile(r"\bjulianday\s*\(", re.I),
     "SQLite-only date arithmetic", "hard"),
    ("strftime",
     re.compile(r"\bstrftime\s*\(", re.I),
     "format specifiers differ (%s vs to_char patterns)", "warn"),
    ("limit-offset",
     re.compile(r"\blimit\s+\d+\s*,\s*\d+", re.I),
     "SQLite's LIMIT a, b is LIMIT b OFFSET a elsewhere", "hard"),
    ("bare-group-by",
     re.compile(r"\bgroup\s+by\b", re.I),
     "PostgreSQL rejects non-aggregated select columns that SQLite allows", "warn"),
]


def check(sql: str) -> list[dict]:
    hits = []
    for name, pat, why, sev in RULES:
        if pat.search(sql or ""):
            hits.append({"rule": name, "severity": sev, "why": why})
    return hits


def refuse(sql: str) -> bool:
    return any(h["severity"] == "hard" for h in check(sql))


def selftest() -> int:
    muts = []
    cases = [
        ("select substr(name, -2) from t", True, "substr-negative"),
        ("select substr(name, 2) from t", False, "substr-negative"),
        ("select round(cast(x as real), 2) from t", True, "round-double"),
        ("select round(x, 2) from t", False, "round-double"),
        ("select `a` from t", True, "backtick-ident"),
        ("select iif(a > 1, 1, 0) from t", True, "iif"),
        ("select julianday('2020-01-01')", True, "julianday"),
        ("select * from t limit 10, 5", True, "limit-offset"),
        ("select * from t limit 5 offset 10", False, "limit-offset"),
    ]
    for sql, want, rule in cases:
        got = refuse(sql)
        muts.append({"mutation": f"{rule}:{sql[:28]}", "caught": got == want})
    # a warn-only construct must not refuse
    muts.append({"mutation": "warn-does-not-refuse",
                 "caught": not refuse("select strftime('%Y', d) from t")})
    muts.append({"mutation": "warn-is-reported",
                 "caught": any(h["rule"] == "strftime" for h in check("select strftime('%Y', d) from t"))})
    ok = all(m["caught"] for m in muts)
    print(json.dumps({"selftest": muts, "ok": ok}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def score(rows: list[dict], sql_of) -> dict:
    """rows need: id, diverged(bool). sql_of(row) -> SQL string."""
    tp = fp = fn = tn = 0
    hard_tp = 0
    for r in rows:
        flagged = refuse(sql_of(r))
        if flagged and r["diverged"]:
            tp += 1
            hard_tp += 1
        elif flagged and not r["diverged"]:
            fp += 1
        elif not flagged and r["diverged"]:
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(prec, 4) if prec is not None else None,
            "recall": round(rec, 4) if rec is not None else None,
            "refusedRate": round((tp + fp) / len(rows), 4) if rows else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--results", default="")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.results:
        print("usage: --results poc/79/results.json | --selftest")
        return 2
    print(json.dumps({"note": "scoring lives in poc/80/score.py"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
