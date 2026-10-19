#!/usr/bin/env python3
"""POC-65 analysis: turn a results file into a coverage/accuracy frontier.

Pure function of `results.json` — no model, no database, no gold lookups. This
is deliberate: the numbers in the document must be re-derivable from a file
that ships with the repository, not from a live rerun.

Terminology, fixed here so it cannot drift:

  coverage       share of questions answered without a human
  accuracy@cov   execution-match accuracy on exactly those questions
  silent         wrong, executed, non-empty result (no runtime signal)
  precision      P(wrong | flagged) — what a reviewer actually experiences
  recall         share of all wrong answers the check catches
  false alarm    flagged answers that were correct

Usage: python3 poc/65/analyze.py poc/65/results.json [--out analysis.json]
"""
from __future__ import annotations

import json
import sys


def pct(x):
    return round(100 * x, 2)


def analyse(doc):
    rows = [r for r in doc["rows"] if r.get("status") == "ok"]
    n = len(doc["rows"])
    N = doc["summary"]["samplesPerQuestion"]
    wrong = [r for r in rows if not r["winner"]["ex_set"]]
    correct = [r for r in rows if r["winner"]["ex_set"]]
    silent = [r for r in wrong if (r["winner"].get("rows") or 0) > 0]

    def curve():
        out = []
        for t in range(1, N + 1):
            auto = [r for r in rows if (r.get("support") or 0) >= t]
            ok = sum(1 for r in auto if r["winner"]["ex_set"])
            out.append({
                "minSupport": t,
                "auto": len(auto),
                "coverage": round(len(auto) / n, 4),
                "accuracy": round(ok / len(auto), 4) if auto else None,
                "escalated": n - len(auto),
                "escalationRate": round((n - len(auto)) / n, 4),
            })
        return out

    def support_table():
        out = {}
        for s in range(1, N + 1):
            grp = [r for r in rows if r.get("support") == s]
            if grp:
                out[str(s)] = {"n": len(grp),
                               "correct": sum(1 for r in grp if r["winner"]["ex_set"]),
                               "accuracy": round(sum(1 for r in grp if r["winner"]["ex_set"]) / len(grp), 4)}
        return out

    def rule_stats(name):
        flagged = [r for r in rows if (r.get("flags") or {}).get(name, {}).get("flag")]
        flagged_wrong = [r for r in flagged if not r["winner"]["ex_set"]]
        silent_ids = {id(r) for r in silent}
        flagged_silent = [r for r in flagged if id(r) in silent_ids]
        checked = [r for r in rows if (r.get("flags") or {}).get(name, {}).get("checked")]
        return {
            "checked": len(checked),
            "flagged": len(flagged),
            "flagRate": round(len(flagged) / len(rows), 4) if rows else None,
            "precision": round(len(flagged_wrong) / len(flagged), 4) if flagged else None,
            "correctBlocked": len(flagged) - len(flagged_wrong),
            "recallAllWrong": round(len(flagged_wrong) / len(wrong), 4) if wrong else None,
            "recallSilent": round(len(flagged_silent) / len(silent), 4) if silent else None,
        }

    def policy(t, block_flags):
        auto = [r for r in rows if (r.get("support") or 0) >= t]
        if block_flags:
            auto = [r for r in auto if not (r.get("flags") or {}).get("any")]
        ok = sum(1 for r in auto if r["winner"]["ex_set"])
        return {"minSupport": t, "blockOnFlag": block_flags, "auto": len(auto),
                "coverage": round(len(auto) / n, 4),
                "accuracy": round(ok / len(auto), 4) if auto else None,
                "escalated": n - len(auto)}

    # The residual that unanimity cannot see: unanimous and still wrong.
    unanimous_wrong = [r for r in wrong if (r.get("support") or 0) == N]
    unanimous_wrong_caught = [r for r in unanimous_wrong if (r.get("flags") or {}).get("any")]
    silent_unanimous = [r for r in unanimous_wrong if (r["winner"].get("rows") or 0) > 0]

    rules = {k: rule_stats(k) for k in ("shape", "fanout", "literal", "degenerate")}
    any_flagged = [r for r in rows if (r.get("flags") or {}).get("any")]
    return {
        "n": n,
        "answered": len(rows),
        "samplesPerQuestion": N,
        "baseline": {
            "ex": round(len(correct) / n, 4) if n else None,
            "exAmongAnswered": round(len(correct) / len(rows), 4) if rows else None,
            "wrong": len(wrong),
            "silent": len(silent),
            "silentShareOfWrong": round(len(silent) / len(wrong), 4) if wrong else None,
            "execOrEmpty": len(wrong) - len(silent),
        },
        "confidenceCurve": curve(),
        "bySupport": support_table(),
        "rules": rules,
        "anyFlag": {
            "flagged": len(any_flagged),
            "flagRate": round(len(any_flagged) / len(rows), 4) if rows else None,
            "precision": round(sum(1 for r in any_flagged if not r["winner"]["ex_set"]) / len(any_flagged), 4)
            if any_flagged else None,
            "correctBlocked": sum(1 for r in any_flagged if r["winner"]["ex_set"]),
            "recallAllWrong": round(sum(1 for r in any_flagged if not r["winner"]["ex_set"]) / len(wrong), 4)
            if wrong else None,
            "recallSilent": round(sum(1 for r in any_flagged if id(r) in {id(x) for x in silent})
                                  / len(silent), 4)
            if silent else None,
        },
        "policies": [policy(t, b) for t in range(1, N + 1) for b in (False, True)],
        "residual": {
            "unanimousWrong": len(unanimous_wrong),
            "caughtByValidators": len(unanimous_wrong_caught),
            "silentUnanimous": len(silent_unanimous),
            "recallOnUnanimousWrong": round(len(unanimous_wrong_caught) / len(unanimous_wrong), 4)
            if unanimous_wrong else None,
        },
        "perDifficulty": {
            d: {
                "n": len([r for r in rows if r.get("difficulty") == d]),
                "accuracy": round(sum(1 for r in rows if r.get("difficulty") == d and r["winner"]["ex_set"])
                                  / max(1, len([r for r in rows if r.get("difficulty") == d])), 4),
                "flagRate": round(sum(1 for r in rows if r.get("difficulty") == d
                                      and (r.get("flags") or {}).get("any"))
                                  / max(1, len([r for r in rows if r.get("difficulty") == d])), 4),
            }
            for d in sorted({r.get("difficulty") for r in rows if r.get("difficulty")})
        },
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "results.json"
    out_path = None
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]
    doc = json.load(open(path))
    a = analyse(doc)
    if out_path:
        json.dump(a, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(a, ensure_ascii=False, indent=1))
    print("\n--- routing (support>=k, flags blocked) ---")
    for p in a["policies"]:
        print("k=%d block=%s  coverage=%.1f%%  accuracy=%s  escalated=%d"
              % (p["minSupport"], p["blockOnFlag"], 100 * p["coverage"],
                 "n/a" if p["accuracy"] is None else "%.1f%%" % (100 * p["accuracy"]),
                 p["escalated"]))


if __name__ == "__main__":
    main()
