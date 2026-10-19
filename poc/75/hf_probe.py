#!/usr/bin/env python3
"""POC-75: can a token we actually hold open a gated dataset?

`eval/eval-plan.yaml` marks E4 (BIRD-Interact) and part of E1's successor plan as
`blocked: dataset gated on HuggingFace`. A gated flag has three distinct causes
that look identical from the outside:

  * the token is absent          -> 401 on any endpoint
  * the token is valid but the account has not accepted the dataset terms
                                 -> 403 (or 200 with an empty file list)
  * the token is valid and accepted, but the repo is private to another org
                                 -> 404

Guessing between them is what produced the wrong "CPU-only blocks evaluation"
attribution earlier. This script reports which one it is, and never prints a
token: every outbound string passes through `redact()` before it is emitted.

    python3 poc/75/hf_probe.py                 # live probe, needs HF_TOKEN*
    python3 poc/75/hf_probe.py --selftest      # no network; redaction + classifier

Exit code is 0 whenever the probe itself ran (a blocked dataset is a finding, not
a crash); 1 only for a broken redactor, i.e. a leak.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

HF = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")

# Names in the order we will try them. GitHub org/repo secrets are injected as
# env vars by name; an undefined secret is simply an empty string, which is why
# the presence check has to happen here rather than in the API.
CANDIDATES = ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HF_API_TOKEN", "HUGGING_FACE_TOKEN")

DEFAULT_REPOS = (
    "birdsql/bird_interact",     # E4 BIRD-Interact Lite
    "xlang-ai/Spider2-Lite",     # E1 successor (SQLite subset)
    "xlang-ai/Spider2",
    "birdsql/bird_mini_dev",     # control: known public, must come back usable
)


def redact(text: str, token: str | None) -> str:
    """Remove the token (and any >=8-char slice of it) from outbound text."""
    if not token:
        return text
    out = text.replace(token, "<redacted>")
    # A truncated echo is the realistic leak (str(e)[:80] on a URL containing
    # the token, a header dump, and so on), so scrub long slices too.
    for i in range(0, max(1, len(token) - 12), 8):
        out = out.replace(token[i:i + 16], "<redacted>")
    return out


def classify(status: int, body: dict | None) -> str:
    """Map an HTTP result onto the four causes above.

    Returns one of: accessible | gated_no_terms | no_token | not_found | error.
    """
    if status == 200:
        if body and body.get("gated"):
            # Metadata is readable, files are not: terms not accepted for this
            # account, or the caller is anonymous.
            return "gated_no_terms"
        return "accessible"
    if status in (401,):
        return "no_token"
    if status in (403,):
        return "gated_no_terms"
    if status == 404:
        return "not_found"
    return "error"


def fetch(url: str, token: str | None, timeout: int = 25) -> tuple[int, dict | None, str]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw), ""
            except Exception:
                return r.status, None, ""
    except urllib.error.HTTPError as e:
        body = e.read()[:400].decode("utf8", "replace")
        return e.code, None, body
    except Exception as e:  # noqa: BLE001 - network shape varies
        return 0, None, str(e)


def probe(repos, token: str | None, who: str = "unknown") -> dict:
    """Probe each repo. Pure function over `fetch`, so it is testable offline."""
    out = {"tokenPresent": bool(token), "identity": who,
           "endpoint": HF, "repos": {}}
    for repo in repos:
        status, body, err = fetch(f"{HF}/api/datasets/{repo}", token)
        verdict = classify(status, body)
        rec = {"status": status, "verdict": verdict,
               "gated": (body or {}).get("gated"),
               "private": (body or {}).get("private"),
               "files": len((body or {}).get("siblings") or []),
               "error": redact(err[:160], token) if err else ""}
        if verdict == "accessible" and rec["files"] == 0:
            # 200 with no siblings on a gated repo is the ambiguous case: the
            # metadata endpoint answered but the tree did not. Ask explicitly.
            s2, b2, e2 = fetch(f"{HF}/api/datasets/{repo}/tree/main", token)
            rec["treeStatus"] = s2
            rec["treeFiles"] = len(b2) if isinstance(b2, list) else 0
            rec["error"] = rec["error"] or (redact(e2[:160], token) if e2 else "")
        out["repos"][repo] = rec
    return out


def whoami(token: str | None) -> tuple[str, dict]:
    if not token:
        return "no-token", {}
    status, body, _err = fetch(f"{HF}/api/whoami-v2", token)
    if status != 200 or not isinstance(body, dict):
        return f"whoami:{status}", {}
    kind = body.get("type") or ("org" if body.get("orgs") else "user")
    name = body.get("name") or "?"
    orgs = [o.get("name") for o in (body.get("orgs") or [])][:3]
    return f"{kind}:{name} orgs={orgs}", {"authType": (body.get("auth") or {}).get("accessToken")}


def selftest() -> int:
    """Three redaction mutations and four classifier mutations."""
    import copy

    muts = []

    # --- redaction: a leaked token must never survive into the report
    tok = "hf_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    samples = [
        f"https://huggingface.co/api/datasets/x?token={tok}",
        "Authorization: Bearer " + tok,
        tok[:20] + "...",                      # truncated echo, the realistic one
    ]
    for i, s in enumerate(samples):
        leaked = tok in redact(s, tok) or (len(tok) > 20 and tok[:16] in redact(s, tok))
        muts.append({"mutation": f"leak-{i}", "caught": not leaked})

    # --- classifier: the four causes must stay distinguishable
    cases = [
        ((200, {"gated": False}), "accessible"),
        ((200, {"gated": "manual"}), "gated_no_terms"),
        ((401, None), "no_token"),
        ((403, None), "gated_no_terms"),
        ((404, None), "not_found"),
    ]
    for (status, body), want in cases:
        got = classify(status, body)
        muts.append({"mutation": f"classify-{status}-{want}", "caught": got == want})

    # --- probe(): token never appears anywhere in the serialised result
    fake = "hf_" + "Z" * 30
    orig = globals()["fetch"]
    def boom(url, token, timeout=25):  # noqa: ARG001
        return 403, None, f"denied for token {fake}"
    globals()["fetch"] = boom
    try:
        rep = json.dumps(probe(["a/b"], fake))
    finally:
        globals()["fetch"] = orig
    muts.append({"mutation": "probe-report-leak", "caught": fake not in rep})

    ok = all(m["caught"] for m in muts)
    print(json.dumps({"selftest": muts, "ok": ok}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--repos", default=",".join(DEFAULT_REPOS))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    # Presence only. Length is enough to distinguish "unset" from "set"; the
    # value itself must never be printed, and these logs are public.
    present = {}
    for name in CANDIDATES:
        v = os.environ.get(name) or ""
        present[name] = {"set": bool(v), "len": len(v)}
        print(f"[secret] {name}: {'set (len=%d)' % len(v) if v else 'MISSING'}")

    token = next((os.environ[n] for n in CANDIDATES if os.environ.get(n)), None)
    who, meta = whoami(token)
    print(f"[identity] {who} {meta}")

    repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    report = probe(repos, token, who)
    report["secrets"] = present
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)

    usable = [r for r, v in report["repos"].items() if v["verdict"] == "accessible"]
    print("[summary] usable:", usable or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
