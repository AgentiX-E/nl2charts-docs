#!/usr/bin/env python3
"""POC-76: Text-to-Chart on Text2Vis (1,985 rows) — CPU only, API model only.

Text2Vis ships one CSV where every row is already a small table plus a question,
a short answer, matplotlib code and the intended chart type. That makes it the
first benchmark in this repository that measures the *whole* text-to-chart path
we care about (read a table, answer, choose a chart) without a GPU or a local
model.

Two arms, same rows, paired:

  R  rules   chart family from question keywords + column names, no model
  L  llm     one DeepSeek call returning {chart, answer, unanswerable}

Three things are reported separately because collapsing them hides the failure
mode that matters: a system can pick the right chart and still answer wrong, and
225 of the 1,985 rows are marked unanswerable from the table alone — a model that
always answers will look fine on chart accuracy and be useless in production.

Answer matching is our own normaliser (case, punctuation, numeric tolerance,
order-insensitive lists), not the paper's GPT-judged metric. It is stricter on
prose and looser on formatting; both are stated wherever the number is quoted.

Usage:
  python3 poc/76/run.py --data /root/data/text2vis/Text2Vis.csv
  python3 poc/76/run.py --selftest
"""
from __future__ import annotations

import argparse
import csv
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

# The dataset uses ~20 labels. Score both on the label and on a family, because
# "Donut" vs "Pie" is a style choice while "Line" vs "Bar" is a different encoding.
FAMILY = {
    "bar": "bar", "column": "bar", "stacked bar": "bar", "grouped bar": "bar",
    "hbar": "bar", "histogram": "histogram",
    "line": "line", "area": "area", "spline": "line",
    "pie": "pie", "donut": "pie", "doughnut": "pie",
    "scatter": "scatter", "dot": "scatter", "bubble": "scatter",
    "box": "box", "boxplot": "box", "box plot": "box", "violin": "box",
    "treemap": "treemap", "waterfall": "waterfall", "subplot": "subplot",
    "radar": "radar", "heatmap": "heatmap", "funnel": "funnel",
    "table": "table", "map": "map", "sunburst": "treemap", "tree": "treemap",
    "gantt": "bar", "bullet": "bar", "lollipop": "bar", "combo": "combo",
}

RULES = [
    (r"\b(time series|over time|trend|by (year|month|quarter|week|day)|growth)\b", "line"),
    (r"\b(distribution|frequency|how many .* fall|histogram|bins?)\b", "histogram"),
    (r"\b(share|proportion|percentage|composition|breakdown|split)\b", "pie"),
    (r"\b(correlation|relationship between|versus|vs\.?|against each other)\b", "scatter"),
    (r"\b(spread|quartile|outlier|median|box ?plot)\b", "box"),
    (r"\b(hierarchy|nested|part of whole.*nested|treemap)\b", "treemap"),
    (r"\b(running total|cumulative|contribution to change|waterfall)\b", "waterfall"),
]

SYS = ("You read a small table and answer one question about it. Reply with one "
       "JSON object and nothing else:\n"
       '{"chart": "<one of bar,line,area,pie,scatter,histogram,box,treemap,waterfall,subplot>", '
       '"answer": "<short answer, or empty if not answerable>", '
       '"unanswerable": <true|false>}\n'
       "Answer only if the table contains the information; otherwise set "
       "unanswerable=true and leave answer empty.")


def family(label: str) -> str:
    k = (label or "").strip().lower().replace("-", " ")
    if k in FAMILY:
        return FAMILY[k]
    for word in k.split():
        if word in FAMILY:
            return FAMILY[word]
    return k


def rule_chart(question: str, cols: list[str]) -> str:
    q = question.lower()
    for pat, fam in RULES:
        if re.search(pat, q):
            return fam
    # A time-ish column with many rows is the strongest schema-only signal.
    if any(re.search(r"(year|month|date|quarter|week|day|time)", c, re.I) for c in cols):
        return "line"
    return "bar"


NUM = re.compile(r"-?\d+(?:\.\d+)?")


def norm_answer(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[\u3000\s]+", " ", t)
    t = t.strip(" .,;:!?\"'`()[]{}%$")
    return t


def answer_match(gold: str, pred: str) -> bool:
    g, p = norm_answer(gold), norm_answer(pred)
    if not g or not p:
        return False
    if g == p:
        return True
    # numeric comparison with a relative tolerance, so 43.5 vs 43.50 passes
    gn, pn = NUM.findall(g), NUM.findall(p)
    if gn and pn and len(gn) == len(pn):
        # Integers (years, counts) must match exactly: a 0.1% tolerance on 2021
        # lets 2022 through, which is the whole answer. Decimals get the tolerance.
        if not any("." in x for x in gn + pn):
            return gn == pn
        try:
            return all(abs(float(a) - float(b)) <= max(1e-6, 1e-3 * abs(float(a)))
                       for a, b in zip(gn, pn))
        except ValueError:
            pass
    # list answers: order-insensitive
    gs, ps = set(g.split(", ")), set(p.split(", "))
    return gs == ps and len(gs) > 1


def parse_reply(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"chart": "", "answer": "", "unanswerable": False, "raw": (text or "")[:120]}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {"chart": "", "answer": "", "unanswerable": False, "raw": (text or "")[:120]}
    return {"chart": str(d.get("chart", "")).strip().lower(),
            "answer": str(d.get("answer", "")).strip(),
            "unanswerable": bool(d.get("unanswerable")),
            "raw": ""}


def table_block(t: str, max_chars: int = 3000, max_rows: int = 40) -> str:
    lines = [l for l in (t or "").split("\n") if l.strip()]
    if len(lines) > max_rows:
        lines = lines[:max_rows] + [f"... ({len(lines) - max_rows} more rows)"]
    out = "\n".join(lines)
    return out[:max_chars]


def one(row, model_call):
    cols = []
    first = (row.get("Table Data") or "").split("\n")
    if first and first[0].strip():
        cols = [c.strip() for c in first[0].split(",")]
    gold_label = row.get("Chart Type") or ""
    gold_fam = family(gold_label)
    unans = str(row.get("unanswerable", "0")) == "1"

    out = {"id": row["ID"], "gold": gold_fam, "goldLabel": gold_label,
           "unanswerable": unans, "cols": len(cols),
           "complexity": row.get("complexity") or "", "split": row.get("set") or ""}

    out["rule"] = rule_chart(row.get("Question", ""), cols)

    if model_call:
        user = ("Table:\n%s\n\nQuestion: %s" % (table_block(row.get("Table Data")), row.get("Question", "")))
        r = model_call([{"role": "system", "content": SYS},
                        {"role": "user", "content": user}])
        p = parse_reply(r["text"])
        out["llm"] = family(p["chart"])
        out["llmRaw"] = p["chart"]
        out["predAnswer"] = p["answer"]
        out["saidUnanswerable"] = p["unanswerable"]
        out["usage"] = r["usage"]
    out["goldAnswer"] = row.get("Answer", "")
    return out


def summarise(rows, n_total, wall, cost, tokenc):
    def acc(arm):
        t = [r for r in rows if r.get(arm)]
        ok = sum(1 for r in t if r[arm] == r["gold"])
        return round(ok / len(t), 4) if t else None

    ans = [r for r in rows if r.get("llm") and not r["unanswerable"]]
    ans_ok = sum(1 for r in ans if answer_match(r["goldAnswer"], r.get("predAnswer", "")))
    joint = sum(1 for r in ans if r["llm"] == r["gold"] and
                answer_match(r["goldAnswer"], r.get("predAnswer", "")))
    un = [r for r in rows if r["unanswerable"]]
    un_ok = sum(1 for r in un if r.get("saidUnanswerable"))
    ansd = [r for r in rows if not r["unanswerable"]]
    fa = sum(1 for r in ansd if r.get("saidUnanswerable"))

    by_complexity = {}
    for key in ("easy", "medium", "hard", "extra hard"):
        g = [r for r in rows if (r.get("complexity") or "") == key]
        if g:
            by_complexity[key] = {
                "n": len(g),
                "rule": round(sum(1 for r in g if r["rule"] == r["gold"]) / len(g), 4),
                "llm": round(sum(1 for r in g if r.get("llm") == r["gold"]) / len(g), 4),
            }
    return {
        "n": len(rows), "nTotal": n_total,
        "ruleChart": acc("rule"), "llmChart": acc("llm"),
        "answerAcc": round(ans_ok / len(ans), 4) if ans else None,
        "jointAcc": round(joint / len(ans), 4) if ans else None,
        "unanswerableN": len(un),
        "unanswerableRecall": round(un_ok / len(un), 4) if un else None,
        "falseAbstain": round(fa / len(ansd), 4) if ansd else None,
        "byComplexity": by_complexity,
        "chartMismatchTop": Counter((r["gold"], r.get("llm")) for r in rows
                                    if r.get("llm") != r["gold"]).most_common(6),
        "tokens": tokenc, "cost_usd": round(cost, 4), "wall_s": round(wall, 1),
        "model": H.MODEL,
    }


def selftest() -> int:
    muts = []
    cases = [
        ("Bar", "bar"), ("Donut", "pie"), ("Box Plot", "box"),
        ("Scatter Plot", "scatter"), ("Stacked Bar", "bar"), ("Line Chart", "line"),
    ]
    for label, want in cases:
        muts.append({"mutation": f"family:{label}", "caught": family(label) == want})
    am = [
        ("43.5", "43.50", True), ("Spain", "spain.", True), ("-1,200", "-1200", False),
        ("Africa, Asia", "Asia, Africa", True), ("2021", "2022", False),
        ("Fragile", "Extreme fragility", False),
    ]
    for g, p, want in am:
        muts.append({"mutation": f"answer:{g}|{p}", "caught": answer_match(g, p) == want})
    # parse must survive a fenced / chatty reply and must not invent a chart
    pr = parse_reply('```json\n{"chart":"Bar","answer":"3","unanswerable":false}\n```')
    muts.append({"mutation": "parse-fenced", "caught": pr["chart"] == "bar" and pr["answer"] == "3"})
    pr2 = parse_reply("I think it is a line chart")
    muts.append({"mutation": "parse-prose-no-json", "caught": pr2["chart"] == ""})
    # a rule must not fire on an unrelated question
    muts.append({"mutation": "rule-default", "caught":
                 rule_chart("what is the total revenue", ["country", "revenue"]) == "bar"})
    muts.append({"mutation": "rule-time", "caught":
                 rule_chart("what is the total revenue", ["year", "revenue"]) == "line"})
    ok = all(m["caught"] for m in muts)
    print(json.dumps({"selftest": muts, "ok": ok}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/root/data/text2vis/Text2Vis.csv")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    rows = list(csv.DictReader(open(args.data, encoding="utf-8")))
    total = len(rows)
    if args.limit:
        rows = rows[:args.limit]

    t0 = time.time()
    call = None if args.no_llm else (lambda msgs: H.call(msgs))

    def work(r):
        try:
            return one(r, call)
        except Exception as e:  # noqa: BLE001 - one row must not kill the run
            return {"id": r.get("ID"), "gold": family(r.get("Chart Type")),
                    "error": str(e)[:120], "unanswerable": False}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        out = list(pool.map(work, rows))

    tokenc = Counter()
    for r in out:
        for k, v in (r.get("usage") or {}).items():
            tokenc[k] += v or 0
    cost = (tokenc["miss"] * H.PRICE["in_miss"] + tokenc["hit"] * H.PRICE["in_hit"]
            + tokenc["out"] * H.PRICE["out"]) / 1e6

    summary = summarise(out, total, time.time() - t0, cost, dict(tokenc))
    doc = {"summary": summary, "rows": out}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
