#!/usr/bin/env python3
"""POC-79, step 1: export a SQLite database into a portable, typed JSON dump.

The third engine in this project is PostgreSQL. Nobody needs a server to test
that: PGlite is PostgreSQL compiled to WASM and runs in Node (and in a browser)
on the CPU, which is exactly the deployment shape our product claims.

Exporting is where the first design decision lives. SQLite columns are
dynamically typed: the declared type is advisory, and the same column can hold
INTEGER in one row and TEXT in the next. PostgreSQL is statically typed, so the
exporter must commit to one type per column — and that commitment is lossy by
construction. The `types` block is therefore part of the result, not an
implementation detail.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

# Declared SQLite affinity -> PostgreSQL type. Anything unknown becomes text,
# because text is the only lossless choice for a column we do not understand.
PG = {
    "INTEGER": "bigint", "INT": "bigint", "BIGINT": "bigint", "SMALLINT": "bigint",
    "TINYINT": "bigint", "REAL": "double precision", "FLOAT": "double precision",
    "DOUBLE": "double precision", "NUMERIC": "numeric", "DECIMAL": "numeric",
    "TEXT": "text", "VARCHAR": "text", "CHAR": "text", "CLOB": "text", "": "text",
    "DATE": "text", "DATETIME": "text", "TIMESTAMP": "text", "BOOLEAN": "boolean",
}


def pg_type(decl: str, values: list) -> str:
    """Declared affinity wins; otherwise infer from the values we actually saw."""
    d = (decl or "").split("(")[0].strip().upper()
    if d:
        return PG.get(d, "text")
    seen = set()
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            seen.add("bool")
        elif isinstance(v, int):
            seen.add("int")
        elif isinstance(v, float):
            seen.add("real")
        elif isinstance(v, (bytes, bytearray)):
            seen.add("blob")
        else:
            seen.add("str")
    if not seen:
        return "text"
    # Mixed types must degrade to text: bigint would reject 'N/A' later.
    return {"int": "bigint", "real": "double precision", "str": "text",
            "bool": "boolean", "blob": "bytea"}.get(sorted(seen)[0], "text") if len(seen) == 1 else "text"


def dump(db_path: str, max_rows: int = 0) -> dict:
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    out = {"path": db_path, "tables": {}, "types": {}, "lossy": []}
    tables = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
    for t in tables:
        cols = [(r[1], r[2]) for r in con.execute(f'PRAGMA table_info("{t}")')]
        rows = con.execute(f'SELECT * FROM "{t}"').fetchall()
        if max_rows:
            rows = rows[:max_rows]
        # Type commitment per column, decided on the full column, not a sample.
        typed = []
        for i, (name, decl) in enumerate(cols):
            vals = [r[i] for r in rows]
            ty = pg_type(decl, vals)
            typed.append({"name": name, "decl": decl, "pg": ty})
            nonnull = [v for v in vals if v is not None]
            if ty == "bigint" and any(isinstance(v, str) for v in nonnull):
                out["lossy"].append({"table": t, "column": name, "why": "bigint with text values"})
        out["tables"][t] = {"columns": typed, "rows": rows}
        out["types"][t] = {c["name"]: c["pg"] for c in typed}
    con.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-rows", type=int, default=0)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    d = dump(args.db, args.max_rows)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    n = sum(len(v["rows"]) for v in d["tables"].values())
    print(json.dumps({"db": os.path.basename(args.db), "tables": len(d["tables"]),
                      "rows": n, "lossy": len(d["lossy"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
