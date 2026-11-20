#!/usr/bin/env python3
"""POC-39b: a POC script may not shadow a module it or a library will import.

POC-04 was red in CI for five consecutive runs, and the traceback blamed duckdb:

    File "poc/04/inspect.py", line 6, in ast
      raw = duckdb.sql("select json_serialize_sql(?)", params=[sql])...
    AttributeError: partially initialized module 'duckdb' has no attribute 'sql'

The bug was not in duckdb, and not in the SQL. `python3 poc/04/inspect.py` puts
`poc/04` at the front of `sys.path`, so when `duckdb/_relation.py` did
`import dataclasses` and `dataclasses.py` did `import inspect`, Python found
`poc/04/inspect.py` -- the script itself -- instead of the standard library. The
module was then executed a *second* time, under the name `inspect`, and re-entered
its own top-level statement `d = ast(sql)`, where it read `duckdb.sql` off a
module that was still half-initialised. The file name was the whole bug.

This is not one unlucky name, and it is not reproducible on a workstation: it
fires only where something imports that name early. Two mechanical rules:

  R1  no POC script's stem may be a standard-library top-level module name
  R2  no POC script's stem may be a package the CI installs

R2 exists because `poc/04/duckdb.py` would break `import duckdb` in its own
directory -- intent is unknowable from the import statement, so the name is
banned outright. The package list is read from the workflows rather than kept in
a second list here: whatever CI installs is exactly what can collide.

Bounds: local helper modules of the same directory (`poc/60/ex.py`, `link.py`,
`metadata.py`) are legal and common, so R2 does *not* use "is imported" as its
test -- `import ex` inside `poc/60/` is a sibling import, not a shadow. Only
stdlib and CI-installed package names are claimed.

Usage:
  python3 poc/39/shadow.py            # report; exit 1 if anything collides
  python3 poc/39/shadow.py --selftest # 6 mutations over both rules
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKIP_PARTS = {"node_modules", "__pycache__", ".git", ".turbo"}
PIP_RE = re.compile(r"pip3? install(.*)")
PKG_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")


def scripts(root: pathlib.Path) -> list[pathlib.Path]:
    out = []
    for p in sorted((root / "poc").rglob("*.py")):
        if SKIP_PARTS & set(p.parts):
            continue
        out.append(p)
    return out


def installed_packages(root: pathlib.Path) -> dict[str, str]:
    """Package names CI pip-installs, normalised, with the workflow as witness."""
    out: dict[str, str] = {}
    wf = root / ".github" / "workflows"
    if not wf.is_dir():
        return out
    for f in sorted(wf.glob("*.yml")):
        for m in PIP_RE.finditer(f.read_text(encoding="utf-8", errors="ignore")):
            # `pip install --quiet duckdb` must yield duckdb, not "quiet": the
            # flags are stripped before tokenising, not filtered afterwards.
            args = re.sub(r"(?:^|\s)--?[A-Za-z][A-Za-z-]*", " ", m.group(1))
            for tok in PKG_RE.findall(args):
                if tok.startswith("-") or tok in {"pip", "install"}:
                    continue
                name = tok.split("==")[0].split(">=")[0].split("<")[0]
                if not name or name[0].isdigit():
                    continue
                if name.endswith((".txt", ".whl", ".py", ".json")):
                    continue
                out.setdefault(name.lower().replace("-", "_"), f.name)
    return out


def scan(root: pathlib.Path, deps: dict[str, str] | None = None) -> dict:
    """Collisions as data, so the selftest can run it against fixtures."""
    files = scripts(root)
    stdlib = set(sys.stdlib_module_names)
    pkgs = installed_packages(root) if deps is None else deps
    collisions = []
    for f in files:
        stem = f.stem
        rel = f.relative_to(root).as_posix()
        if stem in stdlib:
            collisions.append({"file": rel, "module": stem, "rule": "R1",
                               "why": "standard-library top-level module"})
        elif stem.lower().replace("-", "_") in pkgs:
            collisions.append({"file": rel, "module": stem, "rule": "R2",
                               "why": f"package installed by {pkgs[stem.lower().replace('-', '_')]}"})
    return {
        "scripts": len(files),
        "stdlib_modules": len(stdlib),
        "installed_packages": sorted(pkgs),
        "collisions": collisions,
        "clean": not collisions,
    }


# ---------------------------------------------------------------- selftest ---

def _fixture(base: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    for rel, body in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return base


DEPS = {"duckdb": "poc.yml", "numpy": "poc.yml"}

CASES = [
    # name, files, expected rule set (empty = must be clean)
    ("clean tree", {
        "poc/04/inspect_ast.py": "import duckdb\n",
        "poc/16/main.py": "import numpy\n",
    }, []),
    ("stdlib shadow: the real POC-04 bug", {
        "poc/04/inspect.py": "import duckdb\n",
        "poc/16/main.py": "import numpy\n",
    }, ["R1"]),
    ("installed-package shadow", {
        "poc/04/duckdb.py": "x = 1\n",
        "poc/04/run.py": "import duckdb\n",
    }, ["R2"]),
    ("both rules at once", {
        "poc/07/json.py": "import duckdb\n",
        "poc/07/duckdb.py": "x = 1\n",
        "poc/07/read.py": "import json\nimport duckdb\n",
    }, ["R1", "R2"]),
    ("collision in a subdirectory still counts", {
        "poc/12/lib/types.py": "y = 1\n",
        "poc/12/main.py": "from types import SimpleNamespace\n",
    }, ["R1"]),
    ("sibling helper modules are legal, not shadows", {
        "poc/60/ex.py": "a = 1\n",
        "poc/60/run.py": "import ex\nimport numpy\n",
        "poc/09/analyse.py": "import numpy\n",
    }, []),
    # The package list is read from the workflow, so the parser is on trial too:
    # a flag leaking into the list would ban a plausible file name by accident.
    ("flags are not package names", {
        ".github/workflows/poc.yml":
            "run: |\n  python3 -m pip install --quiet duckdb -r req.txt\n",
        "poc/04/quiet.py": "import duckdb\n",
        "poc/04/inspect_ast.py": "import duckdb\n",
    }, [], True),
]


def selftest() -> int:
    failures = []
    for case in CASES:
        name, files, want = case[0], case[1], case[2]
        # The workflow parser is only exercised when deps are read from the tree.
        auto = len(case) > 3 and case[3]
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(pathlib.Path(td), files)
            deps = None if auto else DEPS
            got = sorted({c["rule"] for c in scan(root, deps)["collisions"]})
            if got != sorted(want):
                failures.append({"case": name, "want": want, "got": got})
            if auto:
                names = set(scan(root, None)["installed_packages"])
                if "quiet" in names or "req_txt" in names:
                    failures.append({"case": name, "want": "flags stripped",
                                     "got": sorted(names)})
    # A rule that fires on the repository we ship is not a rule, it is a broken
    # build, so the real tree is part of the test and not just the fixtures.
    real = scan(ROOT)
    print(json.dumps({"cases": len(CASES), "failures": failures,
                      "real_tree": {"scripts": real["scripts"],
                                    "packages": real["installed_packages"],
                                    "collisions": real["collisions"]}},
                     ensure_ascii=False, indent=1))
    return 1 if failures or not real["clean"] else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    r = scan(ROOT)
    for c in r["collisions"]:
        print(f"{c['file']}: {c['module']} collides ({c['rule']}: {c['why']})",
              file=sys.stderr)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
