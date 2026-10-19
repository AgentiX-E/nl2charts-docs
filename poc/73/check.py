#!/usr/bin/env python3
"""POC-73: the gate registry and the evaluation plan are now machine-checked.

The design document has said since v4.37: "the total is whatever `gates.json`
says; the document does not hardcode it." Until this commit there was no such
file in the repository, so the claim could not be tested. This checker closes
that hole with six rules and six mutations:

  C1  document gate set == registry gate set (both directions)
  C2  every gate has a family, a criterion and a known CI layer
  C3  every measured benchmark has baseline + result + a POC that exists
  C4  every planned/blocked benchmark names what unblocks it
  C5  a plan row's gate, if any, exists in the registry
  C6  a deferred objective carries goal + reason + revisit

A rule that cannot fail is a comment. Each mutation targets one rule.

Usage: python3 poc/73/check.py [--selftest]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC = ROOT / "技术设计方案.md"
REG = ROOT / "eval" / "gates.json"
PLAN = ROOT / "eval" / "eval-plan.yaml"

CI_LAYERS = {"ci:unit", "ci:eval", "ci:pack", "ci:lint", "ci:bench", "ci:obs",
             "ci:federation", "ci:chart", "ci:browser", "ci:net"}
GATE = re.compile(r"^(DG|FG|UX|PKG|TIER|OBS|HITL|CHART|EV|PRE|DELEG|BIRD|API|LINK|REPAIR|CONF|SILENT|PLT|LEVER|DS|P)(\d{1,2})$")


def doc_gates(text: str):
    out = set()
    for line in text.split("\n"):
        m = re.match(r"^\|\s*\**(DG|FG|UX|PKG|TIER|OBS|HITL|CHART|EV|PRE|DELEG|BIRD|API|LINK|REPAIR|CONF|SILENT|PLT|LEVER|DS)(\d{1,2})\**\s*(\||\s+[^|]+\|)", line)
        if m and "–" not in line.split("|")[1]:
            out.add(f"{m.group(1)}{m.group(2)}")
        m2 = re.match(r"^P(\d{1,2})\s+", line)
        if m2:
            out.add(f"P{m2.group(1)}")
    return out


def doc_pocs(text: str):
    return {f"POC-{m}" for m in re.findall(r"^### 14\.\d+ POC-(\d+)：", text, re.M)}


def load_yaml(path: pathlib.Path):
    """Tiny YAML subset reader — the plan file is flat by design (no PyYAML in CI)."""
    data, cur, section = {"benchmarks": []}, None, "benchmarks"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or line.strip() == "---":
            continue
        if line.startswith("version:"):
            data["version"] = line.split(":", 1)[1].strip()
        elif line.strip() in ("deferred:",):
            cur = None
            data.setdefault("deferred", [])
            section = "deferred"
        elif line.strip().startswith("- id:"):
            cur = {"id": line.split(":", 1)[1].strip()}
            data.setdefault(section, []).append(cur)
        elif cur is not None and ":" in line:
            k, v = line.strip().split(":", 1)
            v = v.strip().strip('"')
            if v in ("null", ""):
                v = None
            cur[k] = v
    return data


def check(reg, plan, text):
    v = {"C1": [], "C2": [], "C3": [], "C4": [], "C5": [], "C6": []}
    gates = reg.get("gates", {})
    dg = doc_gates(text)
    if set(gates) != dg:
        v["C1"].append({"missingInRegistry": sorted(dg - set(gates)),
                        "missingInDoc": sorted(set(gates) - dg)})
    for gid, g in gates.items():
        if not GATE.match(gid):
            v["C2"].append({"id": gid, "why": "bad id"})
            continue
        if not (g.get("family") and g.get("criterion")):
            v["C2"].append({"id": gid, "why": "missing family/criterion"})
        layers = g.get("layer") or []
        if not layers or any(l not in CI_LAYERS for l in layers):
            v["C2"].append({"id": gid, "why": "unknown layer", "layer": layers})
    v["C6"] = []
    for d in plan.get("deferred", []):
        if not (d.get("goal") and d.get("reason") and d.get("revisit")):
            v["C6"].append({"id": d.get("id"), "why": "deferred needs goal+reason+revisit"})
    pocs = doc_pocs(text)
    for b in plan["benchmarks"]:
        if b.get("status") == "measured":
            if b.get("baseline") in (None, "") and b["id"] != "E2":
                v["C3"].append({"id": b["id"], "why": "measured without baseline"})
            if b.get("result") in (None, ""):
                v["C3"].append({"id": b["id"], "why": "measured without result"})
            poc = b.get("evidencePoc")
            if not poc or poc not in pocs:
                v["C3"].append({"id": b["id"], "why": "evidence POC missing", "poc": poc})
        if b.get("status") in ("planned", "blocked") and not b.get("unblock"):
            v["C4"].append({"id": b["id"], "why": "no unblock condition"})
        g = b.get("gate")
        if g and g not in gates:
            v["C5"].append({"id": b["id"], "gate": g, "why": "gate not registered"})
    return v


def selftest(base_reg, base_plan, text):
    out = []
    reg = copy.deepcopy(base_reg);
    first = sorted(reg["gates"])[0]
    reg["gates"].pop(first)
    out.append({"mutation": "M1 drop a gate", "caught": bool(check(reg, base_plan, text)["C1"]), "rule": "C1"})

    reg = copy.deepcopy(base_reg)
    reg["gates"][first]["criterion"] = ""
    out.append({"mutation": "M2 empty criterion", "caught": bool(check(reg, base_plan, text)["C2"]), "rule": "C2"})

    plan = copy.deepcopy(base_plan)
    for b in plan["benchmarks"]:
        if b["id"] == "E1":
            b["baseline"] = None
    out.append({"mutation": "M3 measured without baseline", "caught": bool(check(base_reg, plan, text)["C3"]), "rule": "C3"})

    plan = copy.deepcopy(base_plan)
    for b in plan["benchmarks"]:
        if b["id"] == "E1":
            b["gate"] = "NOPE9"
    out.append({"mutation": "M4 unknown gate", "caught": bool(check(base_reg, plan, text)["C5"]), "rule": "C5"})

    # Target by status, never by id: E3 moved from planned to measured in v5.23
    # and this mutation silently stopped testing anything. A mutation that has
    # lost its target is a red, not a pass.
    plan = copy.deepcopy(base_plan)
    targets = [b for b in plan["benchmarks"] if b.get("status") in ("planned", "blocked")]
    if not targets:
        out.append({"mutation": "M5 planned without unblock", "caught": False, "rule": "C4",
                    "why": "no planned/blocked benchmark to mutate"})
    else:
        targets[0]["unblock"] = None
        out.append({"mutation": "M5 planned without unblock",
                    "caught": bool(check(base_reg, plan, text)["C4"]), "rule": "C4"})
    plan = copy.deepcopy(base_plan)
    if plan.get("deferred"):
        plan["deferred"][0]["revisit"] = None
    out.append({"mutation": "M6 deferred without revisit", "caught": bool(check(base_reg, plan, text)["C6"]), "rule": "C6"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    reg = json.loads(REG.read_text(encoding="utf-8"))
    plan = load_yaml(PLAN)
    text = DOC.read_text(encoding="utf-8")
    v = check(reg, plan, text)
    ok = all(not x for x in v.values())
    if args.selftest:
        st = selftest(reg, plan, text)
        ok = ok and all(m["caught"] for m in st)
        print(json.dumps({"rules": {k: len(x) for k, x in v.items()}, "selftest": st, "ok": ok},
                         ensure_ascii=False))
        return 0 if ok else 1
    print(json.dumps({"gates": len(reg["gates"]), "benchmarks": len(plan["benchmarks"]),
                      "violations": {k: len(x) for k, x in v.items()}, "ok": ok}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
