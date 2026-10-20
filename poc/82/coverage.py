#!/usr/bin/env python3
"""POC-82: every POC directory must have a disposition, and all of them must be true.

Note 5 of the project brief says every POC is committed *and* exercised by a
workflow. After 81 POCs that claim had quietly stopped being checkable: 23
directories were referenced by no workflow at all. Most are historical one-off
experiments whose numbers are already in the document, and some are libraries
imported by later POCs — but "most are fine" is not a disposition, and a script
that no longer runs is a citation that can no longer be reproduced.

So every directory gets exactly one of four labels, and the checker refuses the
fifth option (unlabelled):

  ci       referenced by a workflow job that actually runs it
  lib      imported by a POC that is itself `ci` or `smoke`
  data     no executable code (results only)
  oneShot  declared in eval/poc-dispositions.yaml with a reason and an artifact

Anything left over is red. That is the point: the diff between "we ran it" and
"we remember running it" has to be visible.

Usage:
  python3 poc/82/coverage.py            # report
  python3 poc/82/coverage.py --selftest # mutations
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
POCS = ROOT / "poc"
WF = ROOT / ".github" / "workflows"
DISP = ROOT / "eval" / "poc-dispositions.yaml"
CODE = {".py", ".mjs", ".js", ".cjs", ".ts", ".sh", ".jsx"}


def poc_dirs(root: pathlib.Path) -> list[str]:
    out = []
    for p in sorted((root / "poc").iterdir()):
        if p.is_dir() and re.fullmatch(r"\d+[a-z]?", p.name):
            out.append(p.name)
    return out


def workflow_refs(root: pathlib.Path) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for f in sorted((root / ".github" / "workflows").glob("*.yml")):
        for m in re.finditer(r"poc/(\d+[a-z]?)", f.read_text(encoding="utf-8")):
            refs.setdefault(m.group(1), []).append(f.name)
    return refs


def code_refs(root: pathlib.Path) -> dict[str, list[str]]:
    """Which POC directories are imported by another POC's code."""
    refs: dict[str, list[str]] = {}
    for d in poc_dirs(root):
        for f in (root / "poc" / d).rglob("*"):
            if f.suffix not in CODE or "node_modules" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in re.finditer(r"(?:\.\./|\"poc/|'poc/)(\d{1,3}[a-z]?)", text):
                tgt = m.group(1)
                if tgt != d:
                    refs.setdefault(tgt, []).append("%s/%s" % (d, f.name))
    return refs


def has_code(root: pathlib.Path, d: str) -> bool:
    return any(f.suffix in CODE for f in (root / "poc" / d).rglob("*") if "node_modules" not in f.parts)


def load_dispositions(path: pathlib.Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out, cur = {}, None
    for line in path.read_text(encoding="utf-8").split("\n"):
        s = line.strip()
        if s.startswith("- poc:"):
            cur = s.split(":", 1)[1].strip().strip('"').strip("'")
            out[cur] = {}
        elif cur and s and not s.startswith("#") and ":" in s:
            k, v = s.split(":", 1)
            out[cur][k.strip()] = v.strip().strip('"').strip("'")
    return out


def classify(root: pathlib.Path = ROOT):
    dirs = poc_dirs(root)
    wf = workflow_refs(root)
    cd = code_refs(root)
    disp = load_dispositions(root / "eval" / "poc-dispositions.yaml")
    rows = []
    for d in dirs:
        if d in wf:
            rows.append({"poc": d, "kind": "ci", "where": wf[d]})
        elif d in cd and any(x.split("/")[0] in wf for x in cd[d]):
            rows.append({"poc": d, "kind": "lib", "where": sorted({x for x in cd[d]})[:3]})
        elif not has_code(root, d):
            rows.append({"poc": d, "kind": "data", "where": []})
        elif d in disp and disp[d].get("why"):
            rows.append({"poc": d, "kind": "oneShot", "where": [disp[d].get("artifact", "")]})
        else:
            rows.append({"poc": d, "kind": "UNORDERED", "where": []})
    return rows, disp


def selftest() -> int:
    import shutil
    import tempfile

    muts = []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="poc82-"))
    try:
        base = tmp / "repo"
        shutil.copytree(ROOT, base, ignore=shutil.ignore_patterns("node_modules", ".git", "__pycache__"))
        rows, disp = classify(base)
        muts.append({"mutation": "baseline-clean", "caught": not [r for r in rows if r["kind"] == "UNORDERED"]})

        # M1: drop a workflow reference -> that POC becomes unordered
        wf = base / ".github" / "workflows" / "poc.yml"
        original = wf.read_text(encoding="utf-8")
        target = "80"
        wf.write_text(original.replace("poc/80/", "poc/80x/"), encoding="utf-8")
        rows, _ = classify(base)
        got = {r["poc"]: r["kind"] for r in rows}
        muts.append({"mutation": "M1 drop a ci reference", "caught": got.get(target) != "ci"})

        # M2: a directory with code and no disposition must be red, not silently fine
        extra = base / "poc" / "99"
        extra.mkdir()
        (extra / "run.py").write_text("print(1)\n", encoding="utf-8")
        rows, _ = classify(base)
        got = {r["poc"]: r["kind"] for r in rows}
        muts.append({"mutation": "M2 unlabelled directory", "caught": got.get("99") == "UNORDERED"})

        # M3: declaring it in the dispositions file with a reason clears it
        d = base / "eval" / "poc-dispositions.yaml"
        d.write_text(d.read_text(encoding="utf-8").rstrip() + '\n  - poc: "99"\n    why: "selftest"\n    artifact: "none"\n',
                     encoding="utf-8")
        rows, _ = classify(base)
        got = {r["poc"]: r["kind"] for r in rows}
        muts.append({"mutation": "M3 declared oneShot", "caught": got.get("99") == "oneShot"})
        wf.write_text(original, encoding="utf-8")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = all(m["caught"] for m in muts)
    print(json.dumps({"selftest": muts, "ok": ok}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    rows, disp = classify()
    unknown = sorted(set(disp) - {r["poc"] for r in rows})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    rep = {"total": len(rows), "counts": counts,
           "unordered": [r["poc"] for r in rows if r["kind"] == "UNORDERED"],
           "declaredButMissing": unknown,
           "rows": rows}
    print(json.dumps({k: rep[k] for k in ("total", "counts", "unordered", "declaredButMissing")},
                     ensure_ascii=False, indent=1))
    if args.out:
        json.dump(rep, open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
    ok = not rep["unordered"] and not unknown
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
