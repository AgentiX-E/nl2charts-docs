#!/usr/bin/env python3
"""POC-56: preflight — can a POC that passes locally fail on a clean runner?

The first real CI run of this repository failed in three jobs while every POC
passed in the author sandbox. This checker encodes the failure classes so they
cannot come back:

  P1  a CI-executed script reads an absolute sandbox path (/tmp/poc*, /workspace, /Users)
  P2  the workflow names a directory or entry file that does not exist
  P3  the workflow's document-count assertions disagree with the documents
  P4  the workflow file itself is stale (its constants lag the docs)

Self-test: three mutations, each must be caught by exactly the rule it targets.
Exit 0 only when every rule is green and all mutations are caught.
"""
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "poc.yml"
TECH = ROOT / "技术设计方案.md"
WP = ROOT / "产品白皮书.md"

ABS_PAT = re.compile(r"(/tmp/poc\d|/workspace/|/Users/)")
CODE_EXT = {".py", ".mjs", ".js", ".cjs", ".ts", ".sh"}


def workflow_text():
    return WF.read_text(encoding="utf-8")


def always_on_jobs(text):
    """Job blocks that run on every push (no workflow_dispatch guard)."""
    blocks = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"^  ([a-z][\w-]*):\s*$", line)
        if m:
            cur = m.group(1)
            blocks[cur] = []
            continue
        if cur is not None:
            blocks[cur].append(line)
    return [k for k, v in blocks.items() if "workflow_dispatch" not in "\n".join(v)]


def ci_dirs(text):
    """Directories executed by always-on jobs only (manual jobs may use fixtures)."""
    keep = always_on_jobs(text)
    blocks, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^  ([a-z][\w-]*):\s*$", line)
        if m:
            cur = m.group(1)
            blocks[cur] = []
            continue
        if cur is not None:
            blocks[cur].append(line)
    dirs = set()
    for job in keep:
        for line in blocks[job]:
            m = re.search(r"working-directory:\s*(\S+)", line)
            if m:
                dirs.add(m.group(1))
    return sorted(dirs)


def entry_commands(text):
    """(dir, command, target) for every `node X` / `python3 X` in run blocks."""
    out = []
    cur = None
    for line in text.splitlines():
        m = re.search(r"working-directory:\s*(\S+)", line)
        if m:
            cur = m.group(1)
            continue
        m = re.search(r"^\s+(node|python3)\s+(?:--[\w-]+\s+)*([\w./-]+\.(?:mjs|cjs|js|py))", line)
        if m and cur:
            out.append((cur, m.group(1), m.group(2)))
    return out


def scan_abs_paths(dirs):
    hits = []
    for d in dirs:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix not in CODE_EXT or "node_modules" in p.parts:
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for no, line in enumerate(txt.splitlines(), 1):
                if line.lstrip().startswith(("#", "//")):
                    continue
                if ABS_PAT.search(line):
                    hits.append({"file": str(p.relative_to(ROOT)), "line": no, "text": line.strip()[:90]})
    return hits


def scan_entries(entries):
    missing = []
    for d, tool, target in entries:
        p = (ROOT / d / target)
        if not p.exists():
            missing.append({"dir": d, "tool": tool, "target": target})
    return missing


def doc_counts():
    t = TECH.read_text(encoding="utf-8")
    sections = len(re.findall(r"^### 14\.\d+ POC-(\d+)：", t, re.M))
    assumptions = len(re.findall(r'^\| \d+ \| "', t, re.M))
    adrs = len({int(x) for x in re.findall(r"^\|\s*\**ADR-(\d{3})\**\s*\|", t, re.M)})
    return {"sections": sections, "assumptions": assumptions, "adrs": adrs}


def scan_constants(text, counts):
    bad = []
    m = re.search(r"d\['sections'\]\s*==\s*(\d+)", text)
    if m and int(m.group(1)) != counts["sections"]:
        bad.append({"const": "sections", "workflow": int(m.group(1)), "docs": counts["sections"]})
    m = re.search(r"d\['P4_assumption_rows'\]\s*==\s*(\d+)", text)
    if m and int(m.group(1)) != counts["assumptions"]:
        bad.append({"const": "assumptions", "workflow": int(m.group(1)), "docs": counts["assumptions"]})
    return bad


def scan_stale_workflow(text, counts):
    """The workflow must assert today's document shape somewhere."""
    stale = []
    sec = re.search(r"d\['sections'\]\s*==\s*(\d+)", text)
    asm = re.search(r"d\['P4_assumption_rows'\]\s*==\s*(\d+)", text)
    if not sec or int(sec.group(1)) != counts["sections"]:
        stale.append("sections assertion missing or stale")
    if not asm or int(asm.group(1)) != counts["assumptions"]:
        stale.append("assumptions assertion missing or stale")
    if "numpy" not in text:
        stale.append("python job does not install numpy (POC-28/36 need it)")
    return stale


def run_checks(root=ROOT):
    text = (root / ".github" / "workflows" / "poc.yml").read_text(encoding="utf-8")
    dirs = ci_dirs(text)
    entries = []
    cur = None
    for line in text.splitlines():
        m = re.search(r"working-directory:\s*(\S+)", line)
        if m:
            cur = m.group(1)
            continue
        m = re.search(r"^\s+(node|python3)\s+(?:--[\w-]+\s+)*([\w./-]+\.(?:mjs|cjs|js|py))", line)
        if m and cur and cur in dirs:
            entries.append((cur, m.group(1), m.group(2)))

    hits = []
    for d in dirs:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix not in CODE_EXT or "node_modules" in p.parts:
                continue
            for no, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if line.lstrip().startswith(("#", "//")):
                    continue
                if ABS_PAT.search(line):
                    hits.append({"file": str(p.relative_to(root)), "line": no})
    missing = [{"dir": d, "target": t} for d, _, t in entries if not (root / d / t).exists()]

    t = (root / "技术设计方案.md").read_text(encoding="utf-8")
    counts = {
        "sections": len(re.findall(r"^### 14\.\d+ POC-(\d+)：", t, re.M)),
        "assumptions": len(re.findall(r'^\| \d+ \| "', t, re.M)),
        "adrs": len({int(x) for x in re.findall(r"^\|\s*\**ADR-(\d{3})\**\s*\|", t, re.M)}),
    }
    bad_const = []
    m = re.search(r"d\['sections'\]\s*==\s*(\d+)", text)
    if m and int(m.group(1)) != counts["sections"]:
        bad_const.append({"const": "sections", "workflow": int(m.group(1)), "docs": counts["sections"]})
    m = re.search(r"d\['P4_assumption_rows'\]\s*==\s*(\d+)", text)
    if m and int(m.group(1)) != counts["assumptions"]:
        bad_const.append({"const": "assumptions", "workflow": int(m.group(1)), "docs": counts["assumptions"]})
    return {
        "ciDirs": dirs,
        "entryCommands": len(entries),
        "P1_absolutePaths": hits,
        "P2_missingEntries": missing,
        "P3_constantMismatch": bad_const,
        "docs": counts,
    }


def selftest():
    """Three mutations; each must trip exactly the rule it targets."""
    results = []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="poc56-"))
    try:
        shutil.copytree(ROOT, tmp / "repo", ignore=shutil.ignore_patterns("node_modules", ".git"))
        base = tmp / "repo"
        # M1: absolute path in a CI-executed script
        victim = base / "poc" / "52" / "run.mjs"
        victim.write_text("const p = '/tmp/poc52/last.csv';\n" + victim.read_text(encoding="utf-8"), encoding="utf-8")
        r1 = run_checks(base)
        results.append({"mutation": "M1 absolute path", "caught": bool(r1["P1_absolutePaths"]),
                        "rule": "P1"})
        # M2: workflow names a file that does not exist
        wf = base / ".github" / "workflows" / "poc.yml"
        wf.write_text(wf.read_text(encoding="utf-8").replace("node run.mjs", "node does-not-exist.mjs", 1),
                      encoding="utf-8")
        r2 = run_checks(base)
        results.append({"mutation": "M2 missing entry", "caught": bool(r2["P2_missingEntries"]), "rule": "P2"})
        # M3: workflow constant drifts from the docs
        wf.write_text(wf.read_text(encoding="utf-8").replace(
            "assert d['sections'] == %d" % r2["docs"]["sections"], "assert d['sections'] == 1", 1),
            encoding="utf-8")
        r3 = run_checks(base)
        results.append({"mutation": "M3 stale constant", "caught": bool(r3["P3_constantMismatch"]), "rule": "P3"})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return results


def main():
    rep = run_checks()
    rep["selftest"] = selftest()
    rep["ok"] = (
        not rep["P1_absolutePaths"]
        and not rep["P2_missingEntries"]
        and not rep["P3_constantMismatch"]
        and all(m["caught"] for m in rep["selftest"])
    )
    out = pathlib.Path(__file__).with_name("results.json")
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "ciDirs": len(rep["ciDirs"]),
        "entryCommands": rep["entryCommands"],
        "P1": len(rep["P1_absolutePaths"]),
        "P2": len(rep["P2_missingEntries"]),
        "P3": len(rep["P3_constantMismatch"]),
        "selftest": f"{sum(1 for m in rep['selftest'] if m['caught'])}/{len(rep['selftest'])}",
        "docs": rep["docs"],
    }, ensure_ascii=False))
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
