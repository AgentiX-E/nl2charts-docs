#!/usr/bin/env python3
"""POC-72: a faithful, budget-bounded replication of Alpha-SQL's inference loop.

Source read (HKUSTDial/Alpha-SQL, MIT, ICML'25), not the paper summary:

  alphasql/algorithm/mcts/reward.py     MajorityVoteRewardModel.get_reward returns
                                        end_node.consistency_score — no trained value
                                        model, so the method needs no fine-tuning.
  alphasql/algorithm/mcts/mcts_action.py  actions: rephrase question, schema selection,
                                        identify column values / functions, SQL generation
                                        (n=5, temperature 0.8), SQL revision (n=5, 0.8).

Running the full MCTS (UCT, depth >2, n=5 per action) on 500 questions is far
outside a POC budget, so this is the same *policy* with a fixed small tree:

  1. rephrase the question once
  2. identify the column values the question mentions once
  3. sample N=4 SQL at temperature 0.8
  4. revise each failed candidate once (error or zero rows)
  5. score every leaf by consistency (cluster size / valid leaves), pick the best

Arms, paired on the same 500 questions:
  base   the POC-65 winner (5 samples, majority by result, temperature 0)
  asql   this loop

The comparison answers the only question that matters here: does importing the
frontier *algorithm* beat our simpler pipeline under the *same* weak generator?

Usage:
  python3 poc/72/run.py --selftest
  python3 poc/72/run.py --data-dir ~/data/bird_mini_dev --workers 8
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "60"))
import ex  # noqa: E402
import run as H  # noqa: E402

N_SAMPLES = 4
TEMP = 0.8
MAX_REVISE = 2

REPHRASE_SYS = ("You rewrite database questions to be explicit. Keep every constraint. "
                "Do not add constraints that are not implied. Output the rewritten question only.")
VALUE_SYS = ("You extract literal values used as filters. For each, give column and value as "
             "`column = value`, one per line. If none, output NONE.")
REVISE_SYS = ("You are a text-to-SQL engine. The query failed or returned no rows. "
              "Diagnose and output one corrected SQLite statement, nothing else.")


def parse_lines(text, limit=6):
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip(" -`\t")
        if s and s.upper() != "NONE":
            out.append(s[:120])
        if len(out) >= limit:
            break
    return out


def gen_prompt(card, question, rephrased, values):
    parts = [card, ""]
    if rephrased and rephrased.strip():
        parts += ["Rewritten question: %s" % rephrased.strip(), ""]
    if values:
        parts += ["Values mentioned in the question (verify against the schema): %s" % "; ".join(values), ""]
    parts += ["Question: %s" % question, "SQL:"]
    return [{"role": "system", "content": "You are a text-to-SQL engine. Output one SQLite statement only."},
            {"role": "user", "content": "\n".join(parts)}]


def revise_prompt(card, question, sql, why):
    return [{"role": "system", "content": REVISE_SYS},
            {"role": "user", "content": "%s\nQuestion: %s\n\nPrevious SQL:\n%s\n\n%s\n\nCorrected SQL:"
                                        % (card, question, sql, why)}]


def consistency(leaves):
    """Alpha-SQL's reward: cluster size over valid leaves (MajorityVoteRewardModel)."""
    valid = [l for l in leaves if l["ok"]]
    if not valid:
        return None, 0.0
    counts = Counter(l["sig"] for l in valid)
    best = max(counts.values())
    winner = next(l for l in valid if counts[l["sig"]] == best)
    return winner, best / len(valid)


def one(q, db_dir, data_dir):
    out = {"id": q["question_id"], "db_id": q["db_id"]}
    db_path = H.find_db(db_dir, q["db_id"])
    if not db_path:
        out["status"] = "db_missing"
        return out
    g = ex.execute(db_path, q["SQL"])
    if not g.ok:
        out["status"] = "gold_error"
        return out
    gold = g.rows
    card = H.schema_card(db_path, q["db_id"], "samples", data_dir, q["question"])

    usage = {"in": 0, "out": 0, "hit": 0, "miss": 0}

    def call(msgs, temp=0.0, max_tokens=400):
        r = H.call(msgs, temperature=temp, max_tokens=max_tokens)
        for k in usage:
            usage[k] += r["usage"].get(k, 0) or 0
        return r["text"]

    try:
        rephrased = call([{"role": "system", "content": REPHRASE_SYS},
                          {"role": "user", "content": q["question"]}], temp=0.7, max_tokens=160)
        values = parse_lines(call([{"role": "system", "content": VALUE_SYS},
                                   {"role": "user", "content": "%s\n\nQuestion: %s"
                                    % (card, q["question"])}], temp=0.0, max_tokens=120))
    except RuntimeError as e:
        out.update(status="llm_failed", error=str(e))
        return out

    leaves = []
    try:
        for _ in range(N_SAMPLES):
            sql, _f = ex.strip_fence(call(gen_prompt(card, q["question"], rephrased, values),
                                          temp=TEMP))
            allowed, why = ex.guard(sql)
            if not allowed:
                leaves.append({"sql": sql, "ok": False, "why": why})
                continue
            res = ex.execute(db_path, sql)
            leaves.append({"sql": sql, "ok": res.ok and len(res.rows) > 0,
                           "sig": signature(res.rows) if res.ok else None,
                           "rows": len(res.rows), "err": (res.error or "")[:120],
                           "empty": res.ok and len(res.rows) == 0})
    except RuntimeError as e:
        out.update(status="llm_failed", error=str(e))
        return out

    # revision: only failed leaves, one pass, bounded
    revised = 0
    for l in leaves:
        if revised >= MAX_REVISE:
            break
        if l["ok"] or not l.get("sql"):
            continue
        why = ("The database rejected it: %s" % l["err"]) if l.get("err") else \
              "It executed but returned zero rows."
        try:
            sql2, _f = ex.strip_fence(call(revise_prompt(card, q["question"], l["sql"], why), temp=TEMP))
        except RuntimeError:
            continue
        revised += 1
        allowed, _ = ex.guard(sql2)
        if not allowed:
            continue
        res = ex.execute(db_path, sql2)
        if res.ok:
            l["revised"] = sql2[:400]
            l["sql"] = sql2
            l["ok"] = len(res.rows) > 0
            l["sig"] = signature(res.rows)
            l["rows"] = len(res.rows)

    winner, score = consistency(leaves)
    out["usage"] = usage
    out["leaves"] = [{k: l.get(k) for k in ("ok", "rows", "sig", "revised")} for l in leaves]
    out["consistency"] = round(score, 4)
    out["revised"] = revised
    if winner is None:
        out.update(status="no_valid_sql")
        return out
    res = ex.execute(db_path, winner["sql"])
    ok = res.ok and ex.compare(res.rows, gold)[1]
    out.update(status="ok", sql=winner["sql"], ex_set=ok,
               base_correct=bool(q.get("_base")), base_sql=q.get("_base_sql"))
    return out


def signature(rows):
    import hashlib
    key = repr(sorted(ex.canon_rows(rows)))
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def summarise(rows, n_total, base_correct):
    ok = [r for r in rows if r["status"] == "ok"]
    j = sum(1 for r in ok if r["ex_set"])
    only_j = sum(1 for r in ok if r["ex_set"] and not r.get("base_correct"))
    only_b = sum(1 for r in ok if r.get("base_correct") and not r["ex_set"])
    u = {"in": 0, "out": 0, "hit": 0, "miss": 0}
    for r in ok:
        for k in u:
            u[k] += (r.get("usage") or {}).get(k, 0) or 0
    cost = (u["miss"] * H.PRICE["in_miss"] + u["hit"] * H.PRICE["in_hit"]
            + u["out"] * H.PRICE["out"]) / 1e6
    return {"n": n_total, "scored": len(ok),
            "base": {"correct": base_correct, "ex": round(base_correct / n_total, 4)},
            "asql": {"correct": j, "ex": round(j / n_total, 4)},
            "deltaPp": round(100 * (j - base_correct) / n_total, 2),
            "mcnemar": {"onlyAsql": only_j, "onlyBase": only_b,
                        "p": round(mcnemar_exact(only_j, only_b), 6)},
            "avgRevised": round(sum(r.get("revised", 0) for r in ok) / len(ok), 2) if ok else None,
            "avgConsistency": round(sum(r.get("consistency", 0) for r in ok) / len(ok), 3) if ok else None,
            "cost_usd": round(cost, 4)}


def selftest():
    cases = []
    leaves = [{"ok": True, "sig": "a"}, {"ok": True, "sig": "a"}, {"ok": True, "sig": "b"},
              {"ok": False, "sig": None}]
    w, s = consistency(leaves)
    cases.append({"case": "consistency picks the majority cluster",
                  "got": (w["sig"], s), "pass": w["sig"] == "a" and abs(s - 2 / 3) < 1e-9})
    w2, s2 = consistency([{"ok": False, "sig": None}])
    cases.append({"case": "no valid leaves", "pass": w2 is None and s2 == 0.0})
    cases.append({"case": "parse values", "got": parse_lines("a = 1\n- b = 'x'\nNONE"),
                  "pass": parse_lines("a = 1\n- b = 'x'\nNONE") == ["a = 1", "b = 'x'"]})
    p = gen_prompt("CARD", "Q", "REPHRASED", ["status = paid"])
    cases.append({"case": "prompt carries rephrase and values",
                  "pass": "REPHRASED" in p[1]["content"] and "status = paid" in p[1]["content"]})
    cases.append({"case": "revise prompt carries error",
                  "pass": "no such column" in revise_prompt("C", "Q", "SELECT 1", "no such column")[1]["content"]})
    for b, c, want in ((5, 0, 0.0625), (7, 3, 0.34375), (0, 0, 1.0)):
        got = mcnemar_exact(b, c)
        cases.append({"case": "mcnemar %d/%d" % (b, c), "got": round(got, 6),
                      "pass": abs(got - want) < 1e-6})
    ok = all(x["pass"] for x in cases)
    return {"cases": cases, "pass": sum(1 for x in cases if x["pass"]),
            "total": len(cases), "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--results", default=os.path.join(HERE, "..", "65", "results.json"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
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
    if not args.data_dir:
        raise SystemExit("--data-dir is required")

    prev = json.load(open(args.results))
    base = {r["id"]: r for r in prev["rows"] if r.get("status") == "ok"}
    n_total = prev["summary"]["n"]
    qfile = None
    for f in glob.glob(os.path.join(args.data_dir, "**", "*.json"), recursive=True):
        if "mini_dev" in os.path.basename(f):
            qfile = f
            break
    qs = json.load(open(qfile, encoding="utf-8"))
    if args.limit:
        qs = qs[: args.limit]
    db_dir = os.path.join(args.data_dir, "databases")
    if not os.path.isdir(db_dir):
        db_dir = args.data_dir
    # base accuracy is computed on the *evaluated subset*, not all 500
    base_correct = sum(1 for q in qs if (base.get(q["question_id"]) or {}).get("winner", {}).get("ex_set"))
    for q in qs:
        b = base.get(q["question_id"])
        q["_base"] = bool(b and b["winner"]["ex_set"])
        q["_base_sql"] = b["winner"]["sql"] if b else ""

    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(one, q, db_dir, args.data_dir) for q in qs]
        for i, f in enumerate(futs):
            try:
                rows.append(f.result())
            except Exception as e:  # noqa: BLE001
                rows.append({"id": qs[i]["question_id"], "status": "crashed", "error": str(e)[:160]})
            if (i + 1) % 50 == 0:
                print("  %d/%d  %.0fs" % (i + 1, len(qs), time.time() - t0), flush=True)

    doc = {"summary": dict(summarise(rows, len(qs), base_correct),
                           wall_s=round(time.time() - t0, 1), model=H.MODEL,
                           nSamples=N_SAMPLES, temperature=TEMP,
                           source="HKUSTDial/Alpha-SQL (MIT) MajorityVoteRewardModel, bounded tree"),
           "rows": rows}
    json.dump(doc, open(args.out, "w"), ensure_ascii=False)
    print(json.dumps(doc["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
