#!/usr/bin/env python3
"""POC-62: can "non-AI first, AI second" be machine-checked?

The plan says milestone A (no AI) ships first, then milestone B adds AI, and
neither may break the other's public surface. That is a testable claim only if
the public surface is a data structure, not a paragraph. So the surface lives in
two manifests (`api-m-a.json`, `api-m-b.json`) and five rules decide whether B
is an additive superset of A.

Rules, each with a concrete failure it prevents:

  A1 no export removed        renaming/removing breaks every consumer at import
  A2 required arity must not grow
                              inserting a required parameter breaks positional
                              call sites silently at runtime, not at build time
  A3 return type identical or explicitly superset
                              widening is fine, narrowing breaks destructuring
  A4 config fields: additions must be optional
                              a new required field makes existing configs invalid
  A5 subpaths survive         moving `core/admin` breaks deep imports

The consumer fixture is the part that makes this more than a schema check: it
lists call sites written against M-A and replays them against M-B, so "minimal
user-side change" is measured as "0 edits, 0 new arguments".
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    return json.load(open(os.path.join(HERE, name), encoding="utf-8"))


def _exports(manifest):
    """Flatten to {(package, subpath, name): spec}."""
    out = {}
    for pkg, pdata in manifest.get("packages", {}).items():
        for sub, sdata in pdata.get("subpaths", {}).items():
            for name, spec in sdata.get("exports", {}).items():
                out[(pkg, sub, name)] = spec
    return out


def _types(manifest):
    return manifest.get("types", {})


def check(old, new):
    """Return {rule: [violation, ...]} between two manifests."""
    v = {"A1": [], "A2": [], "A3": [], "A4": [], "A5": []}
    oe, ne = _exports(old), _exports(new)

    for key, spec in oe.items():
        pkg, sub, name = key
        if key not in ne:
            # A5 is about subpaths, A1 about symbols: a removed subpath with all
            # its symbols gone is reported once, as A5.
            if not any((pkg, sub, n) in ne for (p, s, n) in ne if p == pkg and s == sub):
                v["A5"].append({"package": pkg, "subpath": sub})
            else:
                v["A1"].append({"package": pkg, "subpath": sub, "export": name})
            continue

        nspec = ne[key]
        if spec.get("kind") == "function" and nspec.get("kind") == "function":
            req = lambda s: sum(1 for p in s.get("params", []) if p.get("required"))  # noqa: E731
            if req(nspec) > req(spec):
                v["A2"].append({"export": name, "oldRequired": req(spec), "newRequired": req(nspec)})
            o_ret, n_ret = spec.get("returns"), nspec.get("returns")
            if o_ret != n_ret:
                allowed = nspec.get("returnsCompatibleWith") or []
                if o_ret not in allowed:
                    v["A3"].append({"export": name, "old": o_ret, "new": n_ret})

    ot, nt = _types(old), _types(new)
    for tname, told in ot.items():
        tnew = nt.get(tname)
        if tnew is None:
            v["A4"].append({"type": tname, "problem": "type removed"})
            continue
        old_fields = set(told.get("fields", {}))
        for fname, fspec in tnew.get("fields", {}).items():
            if fname in old_fields:
                if fspec.get("required") and not told["fields"][fname].get("required") \
                        and not told["fields"][fname].get("requiredAlways"):
                    v["A4"].append({"type": tname, "field": fname, "problem": "became required"})
            elif fspec.get("required") and not fspec.get("optionalForCompatibility"):
                v["A4"].append({"type": tname, "field": fname, "problem": "new required field"})
        for fname in old_fields - set(tnew.get("fields", {})):
            v["A4"].append({"type": tname, "field": fname, "problem": "field removed"})
    return v


def replay(consumer, new):
    """Replay M-A call sites against a manifest. Returns per-site results."""
    ne = _exports(new)
    out = []
    for site in consumer["callSites"]:
        key = (site["package"], site["subpath"], site["export"])
        spec = ne.get(key)
        if spec is None:
            out.append({"site": site["id"], "ok": False, "why": "missing export"})
            continue
        params = spec.get("params", [])
        need = sum(1 for p in params if p.get("required"))
        have = site["argc"]
        out.append({"site": site["id"], "ok": have >= need and have <= len(params),
                    "why": "" if have >= need else "needs %d args, site passes %d" % (need, have)})
    return out


def selftest():
    """Five mutations, one per rule. A rule that cannot fail proves nothing."""
    a = load("api-m-a.json")
    b = load("api-m-b.json")
    res = []

    def mutate(fn, rule):
        c = json.loads(json.dumps(b))
        fn(c)
        v = check(a, c)
        res.append({"rule": rule, "caught": bool(v[rule]), "all": {k: len(x) for k, x in v.items()}})

    def drop_export(c):
        del c["packages"]["@agentix-e/nl2charts-spec"]["subpaths"]["."]["exports"]["ChartSpec"]

    def add_required_param(c):
        e = c["packages"]["@agentix-e/nl2charts-core"]["subpaths"]["."]["exports"]["createRunner"]
        e["params"].insert(0, {"name": "must", "required": True, "type": "boolean"})

    def narrow_return(c):
        e = c["packages"]["@agentix-e/nl2charts-core"]["subpaths"]["."]["exports"]["createRunner"]
        e["returns"] = "RunnerInternal"

    def new_required_field(c):
        c["types"]["RunnerConfig"]["fields"]["apiKey"] = {"required": True, "type": "string"}

    def drop_subpath(c):
        del c["packages"]["@agentix-e/nl2charts-core"]["subpaths"]["./admin"]

    mutate(drop_export, "A1")
    mutate(add_required_param, "A2")
    mutate(narrow_return, "A3")
    mutate(new_required_field, "A4")
    mutate(drop_subpath, "A5")

    ok = all(x["caught"] for x in res)
    return {"mutations": res, "pass": sum(1 for x in res if x["caught"]), "total": len(res), "ok": ok}


def main():
    a, b = load("api-m-a.json"), load("api-m-b.json")
    consumer = load("consumer-m-a.json")
    v = check(a, b)
    replay_res = replay(consumer, b)
    st = selftest()
    violations = {k: len(x) for k, x in v.items()}
    rep = {
        "milestoneA": a["version"],
        "milestoneB": b["version"],
        "exportsA": len(_exports(a)),
        "exportsB": len(_exports(b)),
        "violations": violations,
        "details": {k: x for k, x in v.items() if x},
        "consumer": {"sites": len(replay_res), "passing": sum(1 for r in replay_res if r["ok"]),
                     "failed": [r for r in replay_res if not r["ok"]]},
        "selftest": {"pass": st["pass"], "total": st["total"], "ok": st["ok"]},
    }
    rep["ok"] = (not any(violations.values())) and rep["consumer"]["passing"] == len(replay_res) and st["ok"]
    json.dump(rep, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: rep[k] for k in ("milestoneA", "milestoneB", "exportsA", "exportsB",
                                          "violations", "consumer", "selftest", "ok")},
                     ensure_ascii=False, indent=1))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
