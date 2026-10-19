#!/usr/bin/env python3
"""POC-71: fetch the nvBench 2.0 dev split (public, MIT-adjacent research repo).

The dataset is not vendored into this repository: it is 3.3 MB of third-party
data with no explicit licence file, so the POC pins the exact blob SHA and
fetches it on demand. Reproducibility comes from the SHA, not from a copy.

Usage: python3 poc/71/fetch.py [--out /tmp/nvbench_dev.json]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.request

REPO = "HKUSTDial/nvBench-2.0"
PATH = "data/nvbench2.0/dev.json"
SHA = "f37c5844d3bf2c823a52ed44e9187d1f56eb7222"   # git blob id, pinned 2026-10-19
SIZE = 3344581
SHA1 = None  # filled on first fetch; printed for the record


def api(url, token=None):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/nvbench_dev.json")
    args = ap.parse_args()
    token = os.environ.get("GH_TOKEN")
    blob = api("https://api.github.com/repos/%s/git/blobs/%s" % (REPO, SHA), token)
    raw = base64.b64decode(blob["content"])
    digest = hashlib.sha1(raw).hexdigest()
    if len(raw) != SIZE:
        print("size mismatch: %d != %d" % (len(raw), SIZE), file=sys.stderr)
        return 1
    open(args.out, "wb").write(raw)
    print(json.dumps({"out": args.out, "bytes": len(raw), "sha1": digest,
                      "items": len(json.loads(raw))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
