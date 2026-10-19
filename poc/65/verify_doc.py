#!/usr/bin/env python3
"""POC-65: the document must quote the numbers the analysis actually produced.

This is the P5 rule (index table, §14.0) applied to one POC: every headline
number in §8.22 and §14.66 is derived here from `analysis.json` and required to
appear in the technical design document. Change the data without changing the
prose and this check goes red — which is the only way "the doc says 57.96%"
stays a fact rather than a memory.

Usage: python3 poc/65/verify_doc.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOC = ROOT / "技术设计方案.md"


def fmts(x, pct=True):
    v = x * 100 if pct else x
    return {"%.2f%%" % v, "%.1f%%" % v}


def scope(doc):
    """Only the POC-65 sections, so an unrelated '99.9%' cannot satisfy a check."""
    i = doc.index("### 8.22")
    j = doc.index("## 9. 发布工程", i)
    k = doc.index("### 14.65")
    m = doc.index("### 14.66", k)
    return doc[i:j] + doc[k:m]


def check(a, doc):
    doc = scope(doc)
    pol = {(p["minSupport"], p["blockOnFlag"]): p for p in a["policies"]}
    auto = pol[(a["samplesPerQuestion"], True)]
    checks = [
        ("baseline EX", a["baseline"]["ex"], 1),
        ("silent share", a["baseline"]["silentShareOfWrong"], 1),
        ("unanimous accuracy", a["bySupport"][str(a["samplesPerQuestion"])]["accuracy"], 1),
        ("validator precision", a["anyFlag"]["precision"], 1),
        ("validator recall", a["anyFlag"]["recallAllWrong"], 1),
        ("routing coverage", auto["coverage"], 1),
        ("routing accuracy", auto["accuracy"], 1),
    ]
    missing = []
    for name, value, _ in checks:
        if not any(f in doc for f in fmts(value)):
            missing.append((name, sorted(fmts(value))))

    # counts that must appear as plain integers
    ints = {
        "wrong": a["baseline"]["wrong"],
        "silent": a["baseline"]["silent"],
        "flagged": a["anyFlag"]["flagged"],
        "auto": auto["auto"],
        "escalated": auto["escalated"],
    }
    for name, n in ints.items():
        if str(n) not in doc:
            missing.append((name, [str(n)]))

    return missing, len(checks) + len(ints)


def check68(doc, r=None):
    i = doc.index("### 8.24"); j = doc.index("## 9. 发布工程", i)
    k = doc.index("### 14.68"); m = doc.index("### 14.69", k)
    seg = doc[i:j] + doc[k:m]
    if r is None:
        r = json.load(open(HERE.parent / "68" / "results.json"))["summary"]
    need = ["%.2f%%" % (r["final"]["ex"] * 100),
            "%+.2fpp" % r["deltaPp"],
            "%.1f%%" % (r["stage2"]["fixed"] / max(1, r["stage2"]["attempted"]) * 100)]
    return [(n, n in seg) for n in need]


def check66(doc, r=None):
    """POC-66 headline numbers, checked inside its own two sections only."""
    i = doc.index("### 8.23"); j = doc.index("## 9. 发布工程", i)
    k = doc.index("### 14.66"); m = doc.index("### 14.67", k)
    seg = doc[i:j] + doc[k:m]
    if r is None:
        r = json.load(open(HERE.parent / "66" / "results.json"))["summary"]
    need = ["%.1f%%" % (r["reason"]["yield"] * 100),
            "%.1f%%" % (r["generic"]["yield"] * 100),
            "p=%s" % ("%.3f" % r["mcnemar"]["p"]).rstrip("0").rstrip("."),
            "$%.4f" % r["cost_usd"]]
    return [(n, n in seg) for n in need]


def main():
    a = json.load(open(HERE / "analysis.json"))
    doc = DOC.read_text(encoding="utf-8")
    if "--selftest" in sys.argv:
        # Three mutations: each must be reported as missing by this check.
        mutations = []
        for label, fn in (
            ("baseline EX", lambda x: x["baseline"].__setitem__("ex", 0.999)),
            ("routing accuracy", lambda x: [p.__setitem__("accuracy", 0.999)
                                            for p in x["policies"]]),
            ("routing coverage", lambda x: [p.__setitem__("coverage", 0.111)
                                            for p in x["policies"]]),
        ):
            import copy
            m = copy.deepcopy(a)
            fn(m)
            miss, _n = check(m, doc)
            mutations.append({"mutation": label, "caught": bool(miss)})
        # POC-66 has its own mutation: a changed yield must be reported
        import copy as _c
        r66 = json.load(open(HERE.parent / "66" / "results.json"))["summary"]
        r66_bad = _c.deepcopy(r66)
        r66_bad["reason"]["yield"] = 0.999
        ok66 = any(not hit for _n, hit in check66(doc, r66_bad))
        mutations.append({"mutation": "poc66 reason yield", "caught": ok66})
        r68 = json.load(open(HERE.parent / "68" / "results.json"))["summary"]
        r68_bad = _c.deepcopy(r68)
        r68_bad["final"]["ex"] = 0.999
        ok68 = any(not hit for _n, hit in check68(doc, r68_bad))
        mutations.append({"mutation": "poc68 final ex", "caught": ok68})
        ok = all(m["caught"] for m in mutations)
        print(json.dumps({"selftest": mutations, "ok": ok}, ensure_ascii=False))
        return 0 if ok else 1

    missing, n = check(a, doc)
    missing += [{"poc66": n} for n, hit in check66(doc) if not hit]
    missing += [{"poc68": n} for n, hit in check68(doc) if not hit]
    ok = not missing
    print(json.dumps({"ok": ok, "checked": n, "missing": missing},
                     ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
