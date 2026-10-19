#!/usr/bin/env python3
"""POC-73: seed the gate registry from the design document.

The document has claimed since v4.37 that "the registry is the source of truth,
the document does not hardcode the total". That was false: there was no registry
in the repository. This script extracts every gate row from §1.10 / §8.6 and
writes `eval/gates.json`, which is then committed and checked by `check.py`.

Seeding is a one-off: after this commit the registry is authored, and the check
fails if the document and the registry drift apart in either direction.

Usage: python3 poc/73/gen.py [--check]
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC = ROOT / "技术设计方案.md"
OUT = ROOT / "eval" / "gates.json"

# Policy, not parsing: which CI layer owns each family. Mirrors the §8.6 table.
LAYER = {
    "DG": ["ci:federation"], "FG": ["ci:federation"], "UX": ["ci:unit"],
    "PKG": ["ci:pack"], "PLT": ["ci:pack"], "TIER": ["ci:bench"],
    "OBS": ["ci:unit", "ci:obs"], "HITL": ["ci:eval", "ci:unit"],
    "CHART": ["ci:unit"], "EV": ["ci:eval"], "PRE": ["ci:lint"],
    "DELEG": ["ci:lint"], "BIRD": ["ci:eval"], "API": ["ci:pack"],
    "LINK": ["ci:eval"], "REPAIR": ["ci:eval"], "CONF": ["ci:eval"],
    "SILENT": ["ci:eval", "ci:unit"], "PLT8": ["ci:pack"], "LEVER": ["ci:eval"],
    "P": ["ci:unit"],
}
FAMILY = re.compile(r"^(DG|FG|UX|PKG|TIER|OBS|HITL|CHART|EV|PRE|DELEG|BIRD|API|LINK|REPAIR|CONF|SILENT|PLT|LEVER)(\d{1,2})$")


def extract(text: str):
    """Same row grammar as poc/39/audit.py, so both agree on what a gate is."""
    gates = {}
    for line in text.split("\n"):
        m = re.match(r"^\|\s*\**(DG|FG|UX|PKG|TIER|OBS|HITL|CHART|EV|PRE|DELEG|BIRD|API|LINK|REPAIR|CONF|SILENT|PLT|LEVER)(\d{1,2})\**\s*(\||\s+[^|]+\|)", line)
        if m and "–" not in line.split("|")[1]:
            gid = f"{m.group(1)}{m.group(2)}"
            gates.setdefault(gid, line.strip())
        m2 = re.match(r"^P(\d{1,2})\s+", line)
        if m2:
            gates.setdefault(f"P{m2.group(1)}", line.strip())
    return gates


def criterion(row: str) -> str:
    cells = [c.strip() for c in row.strip("|").split("|")]
    # gate tables are either 3-4 cells (criterion last) or PLT-style judgement tables
    return (cells[-1] if len(cells) >= 3 else row)[:220]


def build(text: str):
    raw = extract(text)
    out = {}
    for gid, row in raw.items():
        m = FAMILY.match(gid)
        fam = m.group(1) if m else "P"
        layers = LAYER.get(gid) or LAYER.get(fam) or ["ci:unit"]
        out[gid] = {
            "family": fam,
            "criterion": criterion(row),
            "layer": layers,
            "source": "技术设计方案.md",
        }
    return dict(sorted(out.items(), key=lambda kv: (kv[1]["family"], int(re.sub(r"\D", "", kv[0]) or 0), kv[0])))


def main():
    text = DOC.read_text(encoding="utf-8")
    gates = build(text)
    if "--check" in sys.argv:
        data = json.loads(OUT.read_text(encoding="utf-8"))
        same = data.get("gates") == gates
        print(json.dumps({"registry": len(data.get("gates", {})), "doc": len(gates), "same": same},
                         ensure_ascii=False))
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"version": "v5.20", "gates": gates}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "gates": len(gates),
                      "families": sorted({g["family"] for g in gates.values()})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
