#!/usr/bin/env python3
"""POC-65: gold-free validators — can a silent error be made decidable?

POC-64 established the ceiling of "ask the model again": only the 19% of wrong
answers that crash or return zero rows produce a signal. The other 81% run
fine and look plausible. If nothing else can look at them, they never enter any
repair or review path.

This module is the "nothing else": four checks that need the question, the SQL,
the schema and the result — never the gold answer.

  SHAPE       a question that asks for one number produced N rows / M columns
  FANOUT      an aggregate over a join is larger than the same aggregate over
              the base table (the classic 1:N inflation)
  LITERAL     a string literal compared with `=`/`IN` does not exist in the
              column it is compared against (or exists only in another case,
              which SQLite treats as a different value)
  DEGENERATE  a 1x1 answer whose only cell is NULL (aggregate over empty set,
              division by zero)

Every check is a pure function of observable state, so it can be mutation-
tested without a model, a network, or a dataset. That matters: a validator that
cannot fail is a validator that certifies everything.

The checks are deliberately conservative. Precision is reported alongside
recall, because a false alarm sends a correct answer to a human and makes the
product slower without making it righter.
"""
from __future__ import annotations

import re
import sqlite3
from urllib.parse import quote

try:
    import sqlglot
    from sqlglot import exp
except ImportError:  # pragma: no cover - the selftest turns this into a hard fail
    sqlglot = None
    exp = None


# ---------------------------------------------------------------- shape

# Questions that ask for a single number. Kept as an explicit list rather than
# "any question with an aggregate", because the question — not the SQL — is the
# specification. The list is English-only: BIRD is English, and the Chinese set
# has its own answer-column spec (POC-9).
SCALAR = re.compile(
    r"\b(how many|how much|number of|count of|count|total|sum|average|avg|mean|"
    r"maximum|minimum|max|min|highest|lowest|ratio|percentage|percent|proportion|share)\b",
    re.I,
)
# ...unless the question also says it wants a list/grouping, in which case
# several rows are legitimate.
NON_SCALAR = re.compile(
    r"\b(each|per|list|which|what are|name|names|top\s*\d+|bottom\s*\d+|"
    r"group|distribution|breakdown|trend|over time|by (?:year|month|day|week|"
    r"quarter|region|category|type|state|country|city|gender|age))\b",
    re.I,
)


def shape_flag(question: str, rows, ncols: int | None = None) -> dict:
    """Would a human reading only the question call this shape wrong?"""
    q = question or ""
    ncols = len(rows[0]) if (ncols is None and rows) else (ncols or 0)
    scalar = bool(SCALAR.search(q))
    non_scalar = bool(NON_SCALAR.search(q))
    if not scalar or non_scalar:
        return {"flag": False, "checked": False, "why": "not a scalar question"}
    if ncols != 1:
        return {"flag": True, "checked": True,
                "why": "scalar question returned %d columns" % ncols}
    if len(rows) != 1:
        return {"flag": True, "checked": True,
                "why": "scalar question returned %d rows" % len(rows)}
    return {"flag": False, "checked": True, "why": "1x1"}


# ---------------------------------------------------------------- sql helpers


def parse(sql: str):
    if sqlglot is None:
        return None
    try:
        return sqlglot.parse_one(sql, read="sqlite")
    except Exception:  # noqa: BLE001 - unparsable means "no opinion", not "wrong"
        return None


def _schema(conn: sqlite3.Connection) -> dict[str, list[str]]:
    out = {}
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%'")]
        for t in tables:
            out[t.lower()] = [r[1].lower() for r in conn.execute('PRAGMA table_info("%s")' % t)]
    except Exception:  # noqa: BLE001
        return {}
    return out


def _ctes(tree) -> set[str]:
    return {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}


def _tables(tree) -> dict[str, str]:
    """alias (lower) -> real table (lower); CTE references are excluded."""
    skip = _ctes(tree)
    m: dict[str, str] = {}
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if not name or name in skip:
            continue
        m[(t.alias_or_name or name).lower()] = name
    return m


def _resolve(schema: dict[str, list[str]], tmap: dict[str, str], col) -> tuple[str | None, str]:
    name = col.name.lower()
    if col.table:
        t = tmap.get(col.table.lower())
        return (t, name) if t else (None, name)
    hits = sorted({t for t in tmap.values() if name in schema.get(t, [])})
    return (hits[0], name) if len(hits) == 1 else (None, name)


def _render_where(tree, tmap, schema, base_table: str, base_alias: str) -> str | None:
    """WHERE clause usable against the base table alone, or None if not.

    If the filter touches any other table, the de-joined query is not the same
    query and the comparison would be meaningless — so we decline to judge.
    """
    where = tree.args.get("where")
    if where is None:
        return ""
    for col in where.find_all(exp.Column):
        t, _n = _resolve(schema, tmap, col)
        if t != base_table:
            return None
    sql = where.this.sql(dialect="sqlite")
    # qualifiers may name an alias that no longer exists once the join is gone
    for alias, table in tmap.items():
        if table == base_table and alias != base_alias:
            sql = re.sub(r'\b%s\.' % re.escape(alias), "", sql, flags=re.I)
    return " WHERE " + sql


def fanout_flag(conn: sqlite3.Connection, sql: str, rows) -> dict:
    """Aggregate-over-join larger than the same aggregate over the base table."""
    tree = parse(sql)
    if tree is None or not isinstance(tree, exp.Select):
        return {"flag": False, "checked": False, "why": "unparsable"}
    if tree.args.get("group") or tree.args.get("having"):
        return {"flag": False, "checked": False, "why": "grouped"}
    joins = list(tree.find_all(exp.Join))
    if not joins:
        return {"flag": False, "checked": False, "why": "no join"}
    projs = tree.expressions
    if len(projs) != 1:
        return {"flag": False, "checked": False, "why": "not a single projection"}
    agg = projs[0]
    if isinstance(agg, exp.Alias):
        agg = agg.this
    kind = None
    if isinstance(agg, exp.Sum):
        kind = "SUM"
    elif isinstance(agg, exp.Count) and not isinstance(agg.this, exp.Distinct):
        kind = "COUNT"
    else:
        # AVG is invariant under duplicated rows, MAX/MIN too: a fan-out does
        # not change them, so flagging would be a false positive by construction.
        return {"flag": False, "checked": False, "why": "aggregate immune to fan-out"}
    if not rows or len(rows) != 1 or rows[0][0] is None:
        return {"flag": False, "checked": False, "why": "no scalar result"}
    try:
        got = float(rows[0][0])
    except (TypeError, ValueError):
        return {"flag": False, "checked": False, "why": "non-numeric result"}

    schema = _schema(conn)
    tmap = _tables(tree)
    # sqlglot renamed this arg to `from_` (a Python keyword workaround); accept
    # both so the validator does not silently stop working on a dependency bump.
    frm = tree.args.get("from") or tree.args.get("from_")
    if frm is None:
        return {"flag": False, "checked": False, "why": "no base table"}
    base = frm.this
    base_table = base.name.lower()
    if base_table not in schema:
        return {"flag": False, "checked": False, "why": "base table not in schema"}
    base_alias = (base.alias_or_name or base_table).lower()

    if kind == "COUNT" and isinstance(agg.this, exp.Star):
        expr = "COUNT(*)"
    else:
        col = agg.this
        if not isinstance(col, exp.Column):
            return {"flag": False, "checked": False, "why": "aggregate over expression"}
        t, name = _resolve(schema, tmap, col)
        if t != base_table:
            # the measure lives on the other side of the join; de-joining would
            # change the question, so we do not judge
            return {"flag": False, "checked": False, "why": "measure not on base table"}
        expr = '%s("%s")' % (kind, name)

    where = _render_where(tree, tmap, schema, base_table, base_alias)
    if where is None:
        return {"flag": False, "checked": False, "why": "filter touches joined table"}
    base_sql = 'SELECT %s FROM "%s"' % (expr, base_table)
    if base_alias != base_table:
        base_sql += ' AS "%s"' % base_alias
    base_sql += where
    try:
        base_val = conn.execute(base_sql).fetchone()[0]
    except Exception as e:  # noqa: BLE001
        return {"flag": False, "checked": False, "why": "base query failed: %s" % str(e)[:60]}
    if base_val is None:
        return {"flag": False, "checked": False, "why": "base aggregate is NULL"}
    base_val = float(base_val)
    inflated = got > base_val * 1.05 if base_val > 0 else got > 0
    return {"flag": bool(inflated), "checked": True,
            "why": "%s %.4g vs base %.4g" % (kind, got, base_val)}


def _value_state(conn, table: str, column: str, literal: str) -> str:
    """ok | case | absent. Case-sensitive, because SQLite's `=` is."""
    q = 'SELECT EXISTS(SELECT 1 FROM "%s" WHERE "%s" = ?), ' \
        'EXISTS(SELECT 1 FROM "%s" WHERE lower("%s") = lower(?))' % (table, column, table, column)
    try:
        exact, folded = conn.execute(q, (literal, literal)).fetchone()
    except Exception:  # noqa: BLE001
        return "unknown"
    if exact:
        return "ok"
    return "case" if folded else "absent"


def literal_flag(conn: sqlite3.Connection, sql: str, limit: int = 3) -> dict:
    """String literals that cannot match the column they are compared to."""
    tree = parse(sql)
    if tree is None:
        return {"flag": False, "checked": False, "why": "unparsable", "hits": []}
    tmap = _tables(tree)
    if not tmap:
        return {"flag": False, "checked": False, "why": "no table", "hits": []}
    schema = _schema(conn)
    pairs: list[tuple[exp.Column, str]] = []
    for node in tree.find_all(exp.EQ):
        left, right = node.this, node.expression
        if isinstance(left, exp.Column) and isinstance(right, exp.Literal) and right.is_string:
            pairs.append((left, right.this))
        elif isinstance(right, exp.Column) and isinstance(left, exp.Literal) and left.is_string:
            pairs.append((right, left.this))
    for node in tree.find_all(exp.In):
        if not isinstance(node.this, exp.Column):
            continue
        for lit in node.expressions or []:
            if isinstance(lit, exp.Literal) and lit.is_string:
                pairs.append((node.this, lit.this))
    hits, checked = [], 0
    for col, lit in pairs[:limit]:
        # `col = ''` is a defined idiom (empty-string sentinel), not a value
        # mismatch; flagging it produced 3 false alarms in the first run.
        if lit == "":
            continue
        table, name = _resolve(schema, tmap, col)
        if not table:
            continue
        checked += 1
        state = _value_state(conn, table, name, lit)
        if state in ("case", "absent"):
            hits.append({"table": table, "column": name, "literal": lit, "state": state})
    return {"flag": bool(hits), "checked": checked > 0, "why": hits, "hits": hits}


def degenerate_flag(rows) -> dict:
    if not rows or len(rows) != 1 or len(rows[0]) != 1:
        return {"flag": False, "checked": False, "why": "not 1x1"}
    return ({"flag": True, "checked": True, "why": "1x1 answer is NULL"}
            if rows[0][0] is None else {"flag": False, "checked": True, "why": "non-null"})


# ---------------------------------------------------------------- one entry point


def validate(db_path: str, question: str, sql: str, rows) -> dict:
    """Run all four checks. Any exception degrades to 'no opinion'."""
    out = {}
    try:
        out["shape"] = shape_flag(question, rows)
    except Exception as e:  # noqa: BLE001
        out["shape"] = {"flag": False, "checked": False, "why": "error: %s" % e}
    if sqlglot is None:
        for k in ("fanout", "literal"):
            out[k] = {"flag": False, "checked": False, "why": "sqlglot missing"}
        out["degenerate"] = degenerate_flag(rows)
        out["any"] = any(v.get("flag") for v in out.values() if isinstance(v, dict))
        return out
    conn = None
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % quote(db_path), uri=True, timeout=5.0)
        out["fanout"] = fanout_flag(conn, sql, rows)
        out["literal"] = literal_flag(conn, sql)
    except Exception as e:  # noqa: BLE001
        out.setdefault("fanout", {"flag": False, "checked": False, "why": "error: %s" % str(e)[:60]})
        out.setdefault("literal", {"flag": False, "checked": False, "why": "error: %s" % str(e)[:60]})
    finally:
        if conn is not None:
            conn.close()
    out["degenerate"] = degenerate_flag(rows)
    out["any"] = any(v.get("flag") for v in out.values() if isinstance(v, dict))
    return out


# ---------------------------------------------------------------- selftest


def selftest() -> dict:
    """Mutation tests: one known-good and one known-bad input per rule.

    The point is not coverage of the code, it is that each rule can name the
    input it is supposed to reject. A rule with no failing example is a comment.
    """
    import os
    import tempfile

    tmp = tempfile.mkdtemp(prefix="poc65-")
    db = os.path.join(tmp, "t.sqlite")
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, status TEXT);"
        "CREATE TABLE orders(id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT);"
        "CREATE TABLE payments(id INTEGER PRIMARY KEY, order_id INTEGER, amount REAL);"
        "INSERT INTO users VALUES (1,'ann','active'),(2,'bob','active'),(3,'cid','inactive');"
        "INSERT INTO orders VALUES (1,1,10.0,'paid'),(2,1,20.0,'paid'),"
        "(3,2,30.0,'refunded'),(4,2,40.0,'paid');"
        # order 1 is paid twice: a SUM over orders joined to payments must inflate
        "INSERT INTO payments VALUES (1,1,10.0),(2,1,10.0),(3,2,20.0),(4,3,30.0),(5,4,40.0);"
    )
    c.commit()
    c.close()

    def run(question, sql, expect_shape=None, expect_fanout=None,
            expect_literal=None, expect_degenerate=None):
        conn = sqlite3.connect("file:%s?mode=ro" % quote(db), uri=True)
        try:
            rows = conn.execute(sql).fetchall()
        except Exception:
            rows = []
        sh = shape_flag(question, rows)
        fo = fanout_flag(conn, sql, rows)
        li = literal_flag(conn, sql)
        dg = degenerate_flag(rows)
        conn.close()
        checks = []
        for name, got, want in (("shape", sh["flag"], expect_shape),
                                ("fanout", fo["flag"], expect_fanout),
                                ("literal", li["flag"], expect_literal),
                                ("degenerate", dg["flag"], expect_degenerate)):
            if want is not None:
                checks.append({"rule": name, "got": got, "want": want, "pass": got == want,
                               "sql": sql[:60], "why": (sh, fo, li, dg)[
                                   ("shape", "fanout", "literal", "degenerate").index(name)]["why"]})
        return checks

    cases = []
    # SHAPE
    cases += run("How many users are there?", "SELECT name FROM users", expect_shape=True)
    cases += run("How many users are there?", "SELECT COUNT(*) FROM users", expect_shape=False)
    cases += run("List the names of users", "SELECT name FROM users", expect_shape=False)
    cases += run("How many orders per user?",
                 "SELECT user_id, COUNT(*) FROM orders GROUP BY user_id", expect_shape=False)
    cases += run("What is the total amount?", "SELECT amount FROM orders", expect_shape=True)
    # FANOUT: order 1 has two payments, so the join doubles its 10.0 -> 120 vs 100
    cases += run("What is the total order amount?",
                 "SELECT SUM(orders.amount) FROM orders JOIN payments "
                 "ON payments.order_id = orders.id", expect_fanout=True)
    # many-to-one is not a fan-out: joining users cannot duplicate an order
    cases += run("What is the total order amount?",
                 "SELECT SUM(amount) FROM orders JOIN users ON orders.user_id = users.id",
                 expect_fanout=False)
    cases += run("What is the total order amount?", "SELECT SUM(amount) FROM orders",
                 expect_fanout=False)
    cases += run("What is the total paid amount?",
                 "SELECT SUM(amount) FROM orders WHERE status = 'paid'", expect_fanout=False)
    cases += run("What is the average amount?",
                 "SELECT AVG(amount) FROM orders JOIN users ON orders.user_id = users.id",
                 expect_fanout=False)
    # LITERAL: exact match ok; wrong case and absent value are silent failures
    cases += run("paid orders", "SELECT id FROM orders WHERE status = 'paid'",
                 expect_literal=False)
    cases += run("paid orders", "SELECT id FROM orders WHERE status = 'PAID'",
                 expect_literal=True)
    cases += run("refunded orders", "SELECT id FROM orders WHERE status = 'refunded'",
                 expect_literal=False)
    cases += run("cancelled orders", "SELECT id FROM orders WHERE status = 'cancelled'",
                 expect_literal=True)
    # empty-string comparison is an idiom, not a missing value
    cases += run("users without a name", "SELECT id FROM users WHERE name IS NULL OR name = ''",
                 expect_literal=False)
    # DEGENERATE: aggregate over an empty filter is NULL, not 0
    cases += run("What is the total amount?",
                 "SELECT SUM(amount) FROM orders WHERE status = 'cancelled'",
                 expect_degenerate=True)
    cases += run("What is the total amount?", "SELECT SUM(amount) FROM orders",
                 expect_degenerate=False)

    ok = all(x["pass"] for x in cases)
    return {"cases": cases, "pass": sum(1 for x in cases if x["pass"]),
            "total": len(cases), "ok": ok}


if __name__ == "__main__":
    import json
    import sys

    r = selftest()
    print(json.dumps({k: v for k, v in r.items() if k != "cases"}, ensure_ascii=False))
    for x in r["cases"]:
        print(("PASS " if x["pass"] else "FAIL ") + x["rule"], x["got"], x["want"], x["why"])
    sys.exit(0 if r["ok"] else 1)
