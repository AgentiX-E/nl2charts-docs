#!/usr/bin/env python3
"""POC-67: can "CPU first, WebGPU optional" be enforced instead of promised?

The product requirement is now explicit: no GPU-only implementation. That is
easy to write in a design document and easy to break with one transitive
dependency — `onnxruntime-gpu`, `@tensorflow/tfjs-node-gpu`, `cuda-*`,
`tensorrt`, `torch`. None of them fail a build; they just make installation
impossible on a laptop, a CI runner, or a browser.

This checker walks every manifest in the repository and classifies:

  forbidden   hard dependency on a GPU-only runtime (dependencies/devDependencies)
  tolerated   optional dependency or peerDependencyMeta optional that accelerates
              with WebGPU but has a CPU path (wonnx, onnxruntime-web)
  clean       nothing matches

The distinction matters: an *optional* WebGPU accelerator degrades to CPU; a
hard GPU runtime does not degrade at all.

Usage: python3 poc/67/no_gpu_deps.py [--root .] [--selftest]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

FORBIDDEN = re.compile(
    r"(^|/)(onnxruntime-gpu|@tensorflow/tfjs-node-gpu|tensorflow-gpu|cuda|cuda-.*|"
    r"tensorrt|torch|@pytorch/.*|pycuda|jax-cuda.*)$",
    re.I,
)
WEBGPU_OPTIONAL = re.compile(r"(wonnx|onnxruntime-web|@webgpu/.*|webgpu)$", re.I)
KEYS_HARD = ("dependencies", "devDependencies")
KEYS_SOFT = ("optionalDependencies",)


def classify(manifest: dict):
    hard, soft = [], []
    for key in KEYS_HARD:
        for name in (manifest.get(key) or {}):
            if FORBIDDEN.search(name):
                hard.append({"key": key, "name": name})
    for key in KEYS_SOFT:
        for name in (manifest.get(key) or {}):
            if FORBIDDEN.search(name):
                hard.append({"key": key, "name": name})
            elif WEBGPU_OPTIONAL.search(name):
                soft.append({"key": key, "name": name})
    # an accelerator listed as a hard dependency is still a hard dependency
    for name in (manifest.get("dependencies") or {}):
        if WEBGPU_OPTIONAL.search(name):
            hard.append({"key": "dependencies", "name": name,
                         "why": "WebGPU accelerator must be optional, not required"})
    return hard, soft


def scan(root: str):
    manifests, hits, soft_hits = [], [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "__pycache__")]
        if "package.json" not in filenames:
            continue
        path = os.path.join(dirpath, "package.json")
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 - a broken manifest is reported, not skipped
            hits.append({"file": os.path.relpath(path, root), "error": str(e)[:80]})
            continue
        rel = os.path.relpath(path, root)
        manifests.append(rel)
        hard, soft = classify(data)
        for h in hard:
            hits.append(dict(h, file=rel))
        for s in soft:
            soft_hits.append(dict(s, file=rel))
    return {"manifests": len(manifests), "files": sorted(manifests)[:12],
            "forbidden": hits, "optionalAccelerators": soft_hits}


def selftest():
    clean = {"name": "a", "dependencies": {"zod": "4.6.7"},
             "optionalDependencies": {"onnxruntime-web": "1.20.0"}}
    gpu_hard = {"name": "b", "dependencies": {"onnxruntime-gpu": "1.20.0"}}
    gpu_dev = {"name": "c", "devDependencies": {"@tensorflow/tfjs-node-gpu": "4.0.0"}}
    gpu_soft_cuda = {"name": "d", "optionalDependencies": {"cuda-toolkit": "12.0.0"}}
    webgpu_hard = {"name": "e", "dependencies": {"wonnx": "0.8.0"}}
    cases = []
    for label, m, want_hard, want_soft in (
        ("clean cpu + optional webgpu", clean, 0, 1),
        ("gpu runtime in dependencies", gpu_hard, 1, 0),
        ("gpu runtime in devDependencies", gpu_dev, 1, 0),
        ("cuda in optionalDependencies", gpu_soft_cuda, 1, 0),
        ("webgpu accelerator as a hard dep", webgpu_hard, 1, 0),
    ):
        hard, soft = classify(m)
        cases.append({"case": label, "hard": len(hard), "soft": len(soft),
                      "pass": len(hard) == want_hard and len(soft) == want_soft})
    return {"cases": cases, "pass": sum(1 for c in cases if c["pass"]),
            "total": len(cases), "ok": all(c["pass"] for c in cases)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        r = selftest()
        print(json.dumps({k: v for k, v in r.items() if k != "cases"}, ensure_ascii=False))
        for c in r["cases"]:
            if not c["pass"]:
                print("FAIL", c)
        return 0 if r["ok"] else 1
    r = scan(os.path.abspath(args.root))
    r["ok"] = not r["forbidden"]
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
