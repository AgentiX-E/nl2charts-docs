#!/usr/bin/env python3
"""POC-60 scoring primitives: read-only guard, execution, result-set comparison.

Everything here is a pure function of its inputs, so it can be unit-tested
without a model or a network. That matters because a wrong comparator silently
inflates or deflates every headline number in the whitepaper.

Comparison rules are stated explicitly rather than inherited, because "EX"
means different things in different papers:

  multiset  row order ignored, duplicate rows significant  (strict)
  set       row order ignored, duplicates collapsed        (BIRD-compatible)

Both are reported. Neither sorts by value, because ORDER BY is not part of
BIRD's execution match.
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections import Counter
from urllib.parse import quote

# ---------------------------------------------------------------- read-only guard

_WRITE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|truncate)\b",
    re.IGNORECASE,
)


def guard(sql: str) -> tuple[bool, str | None]:
    """Reject anything that could mutate the database.

    A generated statement that writes is a hard failure, not a warning: the
    product promises read-only analytics, so one `DROP` in a demo is enough to
    lose the user's database. The check runs before execution, never after.
    """
    s = strip_comments(sql)
    if not s.strip():
        return False, "GUARD_EMPTY"
    head = s.lstrip().split(None, 1)[0].lower()
    if head not in ("select", "with", "explain"):
        return False, "GUARD_NOT_READ_ONLY"
    # `WITH x AS (DELETE ... RETURNING ...)` is legal in SQLite, so the first
    # token is not sufficient evidence.
    if _WRITE.search(s):
        return False, "GUARD_WRITE_KEYWORD"
    return True, None


def strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def strip_fence(text: str) -> tuple[str, bool]:
    """Remove a markdown code fence; report whether one was present.

    ADR-124 requires the provider layer to do this. Measured here because a
    fence that reaches the executor is a syntax error, not a style issue.
    """
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_+-]*\s*", "", t)
        t = re.sub(r"```\s*$", "", t)
        return t.strip(), True
    return t, False


def normalize_sql(sql: str) -> str:
    s = strip_comments(sql).strip().rstrip(";").strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()


# ---------------------------------------------------------------- execution


class ExecResult:
    __slots__ = ("ok", "rows", "error", "ms")

    def __init__(self, ok, rows=None, error=None, ms=0.0):
        self.ok = ok
        self.rows = rows if rows is not None else []
        self.error = error
        self.ms = ms


def execute(db_path: str, sql: str, timeout_s: float = 30.0) -> ExecResult:
    """Run one statement on a read-only connection."""
    uri = "file:%s?mode=ro" % quote(db_path)
    t0 = time.perf_counter()
    conn = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        deadline = t0 + timeout_s
        # A progress handler is the only portable way to interrupt a runaway
        # cross join; `timeout=` only covers lock waits.
        conn.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 10000)
        cur = conn.execute(sql)
        rows = cur.fetchall()
        return ExecResult(True, rows, None, (time.perf_counter() - t0) * 1000)
    except Exception as e:  # noqa: BLE001 - the message is the evidence
        msg = "%s: %s" % (type(e).__name__, e)
        return ExecResult(False, [], msg, (time.perf_counter() - t0) * 1000)
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------- comparison


def canon_cell(v):
    """Normalise one cell to a comparable token.

    Floats are rounded rather than compared exactly: `sum(amount)` and
    `amount + amount + ...` differ in the last bits, and calling that wrong
    would understate accuracy for no reason. 4 decimals is finer than any
    monetary answer in these schemas.
    """
    if v is None:
        return ("null",)
    if isinstance(v, bool):
        return ("num", float(int(v)))
    if isinstance(v, (int, float)):
        f = round(float(v), 4)
        if f == int(f) and abs(f) < 1e15:
            return ("num", float(int(f)))
        return ("num", f)
    if isinstance(v, bytes):
        try:
            return ("str", v.decode("utf-8"))
        except UnicodeDecodeError:
            return ("bytes", v.hex())
    return ("str", str(v))


def canon_rows(rows):
    return [tuple(canon_cell(c) for c in r) for r in rows]


def compare(pred_rows, gold_rows):
    """Return (multiset_match, set_match) under the rules in the module docstring."""
    p = canon_rows(pred_rows)
    g = canon_rows(gold_rows)
    multiset = Counter(p) == Counter(g)
    set_match = set(p) == set(g)
    return multiset, set_match


def column_count(rows):
    return len(rows[0]) if rows else 0


# ---------------------------------------------------------------- voting


def majority(samples):
    """Pick the modal SQL by normalised text; ties resolve to the earliest.

    `samples` is a list of (sql, ok) in generation order.
    """
    if not samples:
        return None
    counts = Counter(normalize_sql(s) for s, _ in samples)
    best = max(counts.values())
    for s, _ in samples:
        if counts[normalize_sql(s)] == best:
            return s
    return samples[0][0]


def vote_stats(samples):
    counts = Counter(normalize_sql(s) for s, _ in samples)
    return {
        "distinct": len(counts),
        "agreement": max(counts.values()) / len(samples) if samples else 0.0,
        "unanimous": len(counts) == 1,
    }
