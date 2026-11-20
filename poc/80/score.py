#!/usr/bin/env python3
"""POC-80, scoring: what does the guard buy, and what does it cost?

The confusion matrix is computed against what POC-79 actually observed, not
against a belief about what "should" diverge:

  diverged := the gold stopped being self-consistent between SQLite and PG
              (the loud failures never reach the comparison, they are already
              refusals at the engine level)

Two questions are answered, and they pull in opposite directions:

  recall     of the divergences we saw, how many would have been refused
  cost       of the queries that were fine, how many would have been refused

The guard only earns its place if the ratio is lopsided. A guard that refuses
20% of correct queries to catch 5 divergences is a worse product than one that
answers and flags.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guard  # noqa: E402


def load_questions(data_dir: str) -> dict:
    f = glob.glob(os.path.join(data_dir, "data", "mini_dev*.json"))
    if not f:
        return {}
    return {q["question_id"]: q for q in json.load(open(f[0], encoding="utf-8"))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(HERE, "..", "79", "results.json"))
    ap.add_argument("--data-dir", default=os.environ.get("BIRD_DATA", "/root/data/bird_mini_dev"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    rows = json.load(open(os.path.abspath(args.results), encoding="utf-8"))["rows"]
    qs = load_questions(args.data_dir)
    if not rows or not qs:
        print(json.dumps({"error": "no input", "results": args.results,
                          "questions": len(qs)}, ensure_ascii=False))
        return 2

    judged = []
    for r in rows:
        q = qs.get(r["id"])
        if not q:
            continue
        # Only questions where both engines produced a comparable gold can
        # "diverge"; an engine error is a loud failure and already excluded.
        if "goldSelfConsistent" not in r:
            continue
        judged.append({"id": r["id"], "db": r["db"],
                       "diverged": r["goldSelfConsistent"] is False,
                       "sql": q["SQL"]})
    if not judged:
        print(json.dumps({"error": "no comparable rows"}, ensure_ascii=False))
        return 2

    score = guard.score(judged, lambda r: r["sql"])
    flagged = [{"id": r["id"], "rules": [h["rule"] for h in guard.check(r["sql"])],
                "diverged": r["diverged"]} for r in judged if guard.check(r["sql"])]

    out = {
        "n": len(judged),
        "diverged": sum(1 for r in judged if r["diverged"]),
        "matrix": score,
        "flaggedSample": flagged[:8],
        "byRule": {},
    }
    for name, _pat, _why, sev in guard.RULES:
        hit = [r for r in judged if any(h["rule"] == name for h in guard.check(r["sql"]))]
        if not hit:
            continue
        out["byRule"][name] = {
            "severity": sev,
            "flagged": len(hit),
            "diverged": sum(1 for r in hit if r["diverged"]),
        }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if args.out:
        json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
