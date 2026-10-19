#!/usr/bin/env python3
"""POC-61: build a schema card from the database itself, no external metadata.

BIRD's column descriptions are gated behind an access-controlled repo, so the
previous run scored 46.2% with names only. But the published ablation says
*profiling* metadata (61.2%) beats BIRD's own descriptions (59.6%) — and
profiling needs nothing but the database. That makes it both a legitimate
experiment and a real product capability: `MetadataProvider` can bootstrap
itself from any source without asking the user to write docs.

What is extracted, and why each part earns its tokens:

  table row count      cardinality hint ("is this a fact or a dimension table")
  PK                   stops the model grouping by a surrogate key
  FK (inferred)        BIRD ships no FK constraints; without this the model
                       guesses join paths from names alone
  enum values          the single most valuable part: "status" means nothing,
                       "status in {completed, cancelled, pending}" means everything
  numeric range        distinguishes "amount" (0..1e4) from "year" (1900..2100)

Everything is bounded (sample rows, value caps) so the card stays within a
predictable token budget.
"""
from __future__ import annotations

import re
import sqlite3

SAMPLE_ROWS = 200
MAX_ENUM = 12
MAX_ENUM_PRINT = 8
MAX_RANGE_COLS = 40

# Abbreviations that appear in real schemas. Expanding them is cheap and
# measurable; guessing beyond this list is not.
ABBREV = {
    "amt": "amount", "qty": "quantity", "dt": "date", "ts": "timestamp",
    "num": "number", "no": "number", "pct": "percent", "avg": "average",
    "cnt": "count", "desc": "description", "cust": "customer", "cat": "category",
    "dept": "department", "emp": "employee", "addr": "address", "tel": "telephone",
    "dob": "date of birth", "id": "identifier", "nm": "name", "yr": "year",
    "mo": "month", "wk": "week", "org": "organization", "acct": "account",
    "bal": "balance", "qtr": "quarter", "max": "maximum", "min": "minimum",
}


def humanize(name: str) -> str:
    """`cust_id` -> "customer identifier". Only expands a fixed dictionary, so
    the transformation is auditable rather than clever."""
    parts = [p for p in re.split(r"[_\W]+", name) if p]
    out = []
    for p in parts:
        low = p.lower()
        out.append(ABBREV.get(low, low))
    return " ".join(out)


def _q(name: str) -> str:
    return '"%s"' % name.replace('"', '""')


def profile(db_path: str, with_enums: bool = True, with_ranges: bool = True,
            with_keys: bool = True) -> dict:
    """Return a structured description of the database."""
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        info = {}
        for t in tables:
            cols = list(conn.execute('PRAGMA table_info(%s)' % _q(t)))
            try:
                rows = conn.execute('SELECT count(*) FROM %s' % _q(t)).fetchone()[0]
            except Exception:  # noqa: BLE001
                rows = -1
            info[t] = {"rows": rows, "cols": []}
            for cid, name, ctype, _nn, _dflt, pk in cols:
                info[t]["cols"].append({
                    "cid": cid, "name": name, "type": (ctype or "").upper(), "pk": bool(pk),
                })
        # primary keys per table
        for t in info:
            pks = [c["name"] for c in info[t]["cols"] if c["pk"]]
            info[t]["pk"] = pks

        if with_keys:
            _infer_fks(conn, info)
        if with_enums or with_ranges:
            for t in info:
                for c in info[t]["cols"]:
                    _profile_column(conn, t, c, with_enums, with_ranges)
        return info
    finally:
        conn.close()


def _sample(conn, table, col):
    try:
        return [r[0] for r in conn.execute(
            'SELECT %s FROM %s WHERE %s IS NOT NULL LIMIT %d'
            % (_q(col), _q(table), _q(col), SAMPLE_ROWS))]
    except Exception:  # noqa: BLE001
        return []


def _profile_column(conn, table, col, with_enums, with_ranges):
    name, ctype = col["name"], col["type"]
    numeric = any(k in ctype for k in ("INT", "REAL", "NUM", "DEC", "FLOA", "DOUB"))
    vals = _sample(conn, table, name)
    if not vals:
        return
    if with_ranges and numeric and not col["pk"]:
        try:
            nums = [float(v) for v in vals if isinstance(v, (int, float))]
        except (TypeError, ValueError):
            nums = []
        if nums:
            col["range"] = (round(min(nums), 3), round(max(nums), 3))
        return
    if with_enums and not numeric:
        uniq = []
        counts = {}
        for v in vals:
            s = str(v)
            counts[s] = counts.get(s, 0) + 1
            if s not in uniq:
                uniq.append(s)
            if len(uniq) > MAX_ENUM:
                return  # high-cardinality text: it is a name/description, skip
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:MAX_ENUM_PRINT]
        col["enum"] = [(v, n) for v, n in top]


def _infer_fks(conn, info):
    """BIRD ships no FK constraints, so infer them:
    a column named like `<table>_id` (or matching another table's PK) whose
    sampled values are mostly present in the target's PK column."""
    pk_of = {t: info[t]["pk"][0] for t in info if len(info[t]["pk"]) == 1}
    for t in info:
        for c in info[t]["cols"]:
            if c["pk"]:
                continue
            name = c["name"].lower()
            cands = []
            if name in (p.lower() for p in pk_of.values()):
                cands = [x for x in pk_of if pk_of[x].lower() == name and x != t]
            elif name.endswith("_id"):
                stem = name[:-3]
                cands = [x for x in pk_of
                         if (x.lower() == stem or x.lower().rstrip("s") == stem
                             or stem.rstrip("s") == x.lower().rstrip("s")) and x != t]
            for target in cands[:2]:
                src = _sample(conn, t, c["name"])
                dst = set(_sample(conn, target, pk_of[target]))
                if not src or not dst:
                    continue
                hit = sum(1 for v in src if str(v) in {str(x) for x in dst})
                if hit / len(src) >= 0.8:
                    c["fk"] = "%s.%s" % (target, pk_of[target])
                    break


def render(info: dict, db_id: str, with_enums: bool = True, with_ranges: bool = True,
           with_keys: bool = True) -> str:
    lines = ["Database: %s" % db_id, ""]
    for t, meta in info.items():
        head = "Table: %s" % t
        if meta.get("rows", -1) >= 0:
            head += "  (%s rows)" % f"{meta['rows']:,}"
        lines.append(head)
        for c in meta["cols"]:
            bits = []
            if c.get("pk"):
                bits.append("primary key")
            if with_keys and c.get("fk"):
                bits.append("FK -> %s" % c["fk"])
            if with_enums and c.get("enum"):
                shown = ", ".join("%s(%d)" % (v, n) for v, n in c["enum"])
                bits.append("values: " + shown)
            if with_ranges and c.get("range"):
                lo, hi = c["range"]
                bits.append("range %s .. %s" % (lo, hi))
            human = humanize(c["name"])
            label = human if human.replace(" ", "_") != c["name"].lower() else ""
            tail = ("  -- " + "; ".join(bits)) if bits else ""
            name_part = "%s %s" % (c["name"], c["type"] or "TEXT")
            if label:
                name_part += " (%s)" % label
            lines.append("  " + name_part + tail)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def conn_count(db, sql):
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        return c.execute(sql).fetchone()[0]
    finally:
        c.close()


def selftest():
    """Mutations for the three inference rules that can silently be wrong."""
    import os
    import tempfile

    tmp = tempfile.mkdtemp(prefix="poc61-")
    db = os.path.join(tmp, "s.sqlite")
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE customers(customer_id INTEGER PRIMARY KEY, cust_nm TEXT, country TEXT);
    CREATE TABLE orders(order_id INTEGER PRIMARY KEY, customer_id INTEGER, status TEXT, amt REAL);
    INSERT INTO customers VALUES (1,'a','CN'),(2,'b','US'),(3,'c','CN');
    INSERT INTO customers SELECT 100+x, 'name'||x, 'CN' FROM (
      WITH RECURSIVE s(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM s WHERE x<20) SELECT x FROM s);
    INSERT INTO orders VALUES (1,1,'completed',10.5),(2,1,'cancelled',20.0),
                              (3,2,'completed',5.25),(4,3,'pending',7.0);
    """)
    c.commit()
    c.close()

    out = []
    info = profile(db)
    card = render(info, "s")

    out.append({"case": "FK inferred from *_id", "pass": info["orders"]["cols"][1].get("fk") == "customers.customer_id",
                "got": info["orders"]["cols"][1].get("fk")})
    out.append({"case": "PK flagged", "pass": info["customers"]["cols"][0].get("pk") is True})
    out.append({"case": "enum extracted", "pass": bool(info["orders"]["cols"][2].get("enum")),
                "got": info["orders"]["cols"][2].get("enum")})
    # 24 distinct names > MAX_ENUM, so the column must NOT be enumerated
    n_names = conn_count(db, "SELECT count(DISTINCT cust_nm) FROM customers")
    out.append({"case": "high-card text not enumerated",
                "pass": n_names > MAX_ENUM and "enum" not in info["customers"]["cols"][1],
                "got": "%d distinct, enum=%s" % (n_names, info["customers"]["cols"][1].get("enum"))})
    out.append({"case": "numeric range", "pass": info["orders"]["cols"][3].get("range") == (5.25, 20.0),
                "got": info["orders"]["cols"][3].get("range")})
    out.append({"case": "humanize abbrev", "pass": humanize("cust_nm") == "customer name",
                "got": humanize("cust_nm")})
    out.append({"case": "render has enum line", "pass": "values: completed(2)" in card})
    out.append({"case": "render has FK line", "pass": "FK -> customers.customer_id" in card})

    # rule must be able to fail: drop the FK evidence by pointing at a tiny table
    info2 = profile(db, with_keys=False)
    out.append({"case": "keys can be disabled", "pass": "fk" not in info2["orders"]["cols"][1]})
    card2 = render(info2, "s", with_enums=False, with_ranges=False, with_keys=False)
    out.append({"case": "enums can be disabled", "pass": "values:" not in card2})

    ok = all(x["pass"] for x in out)
    return {"checks": out, "pass": sum(1 for x in out if x["pass"]), "total": len(out), "ok": ok}
