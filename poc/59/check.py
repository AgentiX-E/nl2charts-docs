#!/usr/bin/env python3
"""POC-59: who owns the benchmark?

Rule: a capability that is fully delegated to a third party inherits that party's
published evidence. Re-running their benchmark adds nothing; what we must verify
is the INTEGRATION: a pinned version, an upstream evidence link, and a probe that
exercises our composition. Self-built capabilities are the opposite: they need a
benchmark of their own.

D1 every capability has an owner in {self, delegated, platform}
D2 delegated -> tool + pin + evidence(https) + probe(POC-n)
D3 self -> gate + benchmark + (measured with probe | planned with plan)
D4 ids are unique
D5 every referenced probe exists in the technical design
Self-test: three mutations, each must trip the rule it targets.
"""
import json, pathlib, re, shutil, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
TECH = ROOT / "技术设计方案.md"
OWNERS = {"self", "delegated", "platform"}


def load(root=ROOT):
    return json.loads((root / "poc" / "59" / "delegation.json").read_text(encoding="utf-8"))


def doc_probes(root=ROOT):
    t = (root / "技术设计方案.md").read_text(encoding="utf-8")
    return {int(x) for x in re.findall(r"^### 14\.\d+ POC-(\d+)：", t, re.M)}


def check(caps, probes):
    v = {"D1": [], "D2": [], "D3": [], "D4": [], "D5": []}
    seen = set()
    for c in caps:
        cid = c.get("id", "<no-id>")
        if cid in seen:
            v["D4"].append(cid)
        seen.add(cid)
        owner = c.get("owner")
        if owner not in OWNERS:
            v["D1"].append({"id": cid, "owner": owner})
            continue
        if owner == "delegated":
            for f in ("tool", "pin", "evidence", "probe"):
                if not c.get(f):
                    v["D2"].append({"id": cid, "missing": f})
            if c.get("evidence") and not str(c["evidence"]).startswith("https://"):
                v["D2"].append({"id": cid, "missing": "evidence-not-https"})
        elif owner == "self":
            for f in ("gate", "benchmark"):
                if not c.get(f):
                    v["D3"].append({"id": cid, "missing": f})
            if c.get("status") == "measured" and not c.get("probe"):
                v["D3"].append({"id": cid, "missing": "probe (status=measured)"})
            if c.get("status") == "planned" and not c.get("plan"):
                v["D3"].append({"id": cid, "missing": "plan (status=planned)"})
            if c.get("status") not in ("measured", "planned"):
                v["D3"].append({"id": cid, "missing": "status"})
        if c.get("probe"):
            m = re.fullmatch(r"POC-(\d+)", str(c["probe"]))
            if not m or int(m.group(1)) not in probes:
                v["D5"].append({"id": cid, "probe": c["probe"]})
    return v


def run(root=ROOT):
    caps = load(root)["capabilities"]
    probes = doc_probes(root)
    v = check(caps, probes)
    counts = {"total": len(caps)}
    for o in OWNERS:
        counts[o] = sum(1 for c in caps if c.get("owner") == o)
    counts["selfMeasured"] = sum(1 for c in caps if c.get("owner") == "self" and c.get("status") == "measured")
    counts["selfPlanned"] = sum(1 for c in caps if c.get("owner") == "self" and c.get("status") == "planned")
    return {"counts": counts, "violations": v,
            "planned": [c["id"] for c in caps if c.get("status") == "planned"],
            "ok": all(not x for x in v.values())}


def selftest():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="poc59-"))
    out = []
    try:
        shutil.copytree(ROOT, tmp / "repo", ignore=shutil.ignore_patterns("node_modules", ".git"))
        base = tmp / "repo"
        data = load(base)

        def first(pred):
            return next(i for i, c in enumerate(data["capabilities"]) if pred(c))

        # M1: delegated without evidence (index chosen by property, not position:
        # the list grows, and a hard-coded index silently tests nothing)
        d1 = json.loads(json.dumps(data))
        del d1["capabilities"][first(lambda c: c.get("owner") == "delegated")]["evidence"]
        (base / "poc" / "59" / "delegation.json").write_text(json.dumps(d1), encoding="utf-8")
        r = run(base); out.append({"mutation": "M1 delegated without evidence", "caught": bool(r["violations"]["D2"]), "rule": "D2"})

        # M2: self measured but no probe
        d2 = json.loads(json.dumps(data))
        d2["capabilities"][first(lambda c: c.get("owner") == "self" and c.get("status") == "measured")].pop("probe", None)
        (base / "poc" / "59" / "delegation.json").write_text(json.dumps(d2), encoding="utf-8")
        r = run(base); out.append({"mutation": "M2 self measured without probe", "caught": bool(r["violations"]["D3"]), "rule": "D3"})

        # M3: unknown owner
        d3 = json.loads(json.dumps(data)); d3["capabilities"][0]["owner"] = "someone-else"
        (base / "poc" / "59" / "delegation.json").write_text(json.dumps(d3), encoding="utf-8")
        r = run(base); out.append({"mutation": "M3 unknown owner", "caught": bool(r["violations"]["D1"]), "rule": "D1"})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def main():
    rep = run()
    rep["selftest"] = selftest()
    rep["ok"] = rep["ok"] and all(m["caught"] for m in rep["selftest"])
    (HERE / "results.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"counts": rep["counts"], "violations": {k: len(v) for k, v in rep["violations"].items()},
                      "planned": rep["planned"],
                      "selftest": f"{sum(1 for m in rep['selftest'] if m['caught'])}/{len(rep['selftest'])}",
                      "ok": rep["ok"]}, ensure_ascii=False))
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
