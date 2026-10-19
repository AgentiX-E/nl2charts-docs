#!/usr/bin/env python3
"""POC-65: recompute flag aggregates from recorded hits (no model, no database).

Why this exists: the first 500-question run (`run 39228705781`) stored, for each
question, the validator verdict *and* the individual literal hits. When a rule
changes, the samples do not have to be regenerated — the new rule is a pure
function of the same hits. That is the difference between a rerun costing $0.35
and ten minutes, and one costing nothing.

The one rule change between the run and this file: `col = ''` is an idiom
(empty-string sentinel), not evidence that a value is missing. The first
version flagged it three times, all on correct answers. Dropping empty hits is
exactly what `validators.literal_flag` now does.

What is *not* recomputed: SHAPE / FANOUT / DEGENERATE. They depend on the
result rows or the parsed SQL, neither of which is stored. Changing any of them
requires a real rerun — and this script says so instead of pretending.

Usage: python3 poc/65/reflag.py poc/65/results.json [--out ...] [--run-id ...]
"""
from __future__ import annotations

import json
import sys


def reflag(row):
    flags = row.get("flags") or {}
    lit = flags.get("literal")
    if isinstance(lit, dict):
        hits = [h for h in (lit.get("hits") or []) if h.get("literal") != ""]
        lit = dict(lit)
        lit["hits"] = hits
        lit["flag"] = bool(hits)
        flags["literal"] = lit
    flags["any"] = any(isinstance(v, dict) and v.get("flag")
                       for k, v in flags.items() if k != "any")
    row["flags"] = flags
    return row


def main():
    path = sys.argv[1]
    out = path
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    run_id = None
    if "--run-id" in sys.argv:
        run_id = sys.argv[sys.argv.index("--run-id") + 1]
    doc = json.load(open(path))
    for r in doc["rows"]:
        if r.get("status") == "ok":
            reflag(r)
    doc["summary"]["flagsRule"] = "validators.literal_flag@v2 (empty literals excluded)"
    doc["summary"]["flagsRecomputedBy"] = "poc/65/reflag.py"
    if run_id:
        doc["summary"]["sourceRun"] = run_id
    json.dump(doc, open(out, "w"), ensure_ascii=False)
    changed = sum(1 for r in doc["rows"] if (r.get("flags") or {}).get("literal", {}).get("flag"))
    print("wrote %s; literal flags now %d" % (out, changed))


if __name__ == "__main__":
    main()
