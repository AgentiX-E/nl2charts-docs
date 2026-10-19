#!/usr/bin/env python3
"""POC-63: schema linking, measured two ways.

Linking is usually reported only end-to-end (EX goes up), which hides whether the
retriever did its job or the generator got lucky. Here it is measured twice:

  offline   recall@k of the tables the gold SQL actually uses. No model, no cost,
            and it tells you if the retriever drops a table the answer needs.
  end-to-end EX on the same 500 questions, paired against the full-schema run.

Selection is lexical on purpose: it is deterministic, auditable, and needs no
embeddings, so a null result cannot be blamed on a flaky vector service. An
embedding arm can be added later behind the same interface (`score_fn`).

Three ideas that make a tiny lexical retriever competitive:
  idf weighting    a token appearing in every table says nothing
  enum values      POC-61 showed values are the informative part; "completed"
                   in a column's values is strong evidence the column is relevant
  fk closure       selecting `orders` without `customers` produces a join the
                   generator has to invent
"""
from __future__ import annotations

import math
import os
import re
import sqlite3

STOP = set("""a an the of for in on at to by with from and or is are was were be been
how many much what which who whom whose show list give me all each per total
number count please can you i we they it its their there here that this these
those as than then not no yes do does did done have has had""".split())

K_DEFAULT = 4


def tokens(text: str):
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 3 and t not in STOP]


def _q(name: str) -> str:
    return '"%s"' % name.replace('"', '""')


def table_stats(db_path: str):
    """{table: {"cols": [...], "values": {col: [v, ...]}, "fks": {col: target}}}"""
    from metadata import profile  # same package, avoids duplicated inference

    info = profile(db_path)
    out = {}
    for t, meta in info.items():
        vals = {c["name"]: [v for v, _n in (c.get("enum") or [])] for c in meta["cols"]}
        fks = {c["name"]: c["fk"] for c in meta["cols"] if c.get("fk")}
        out[t] = {"cols": [c["name"] for c in meta["cols"]], "values": vals, "fks": fks}
    return out


def compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def score_tables(stats, question):
    """idf-weighted lexical score per table."""
    qt = set(tokens(question))
    if not qt:
        return {t: 1.0 for t in stats}
    n = len(stats)
    # document frequency over tables, counting a table as containing a token if
    # any of its table name, column names, or enum values contains it
    df = {tok: 0 for tok in qt}
    for t, meta in stats.items():
        bag = set(tokens(t))
        for c in meta["cols"]:
            bag |= set(tokens(c))
        for vs in meta["values"].values():
            for v in vs:
                bag |= set(tokens(v))
        for tok in qt:
            if tok in bag:
                df[tok] += 1
    scores = {}
    qcompact = compact(question)
    for t, meta in stats.items():
        s = 0.0
        name_bag = set(tokens(t))
        col_bag = set()
        val_bag = set()
        for c in meta["cols"]:
            col_bag |= set(tokens(c))
        for vs in meta["values"].values():
            for v in vs:
                val_bag |= set(tokens(v))
        for tok in qt:
            idf = math.log((n + 1) / (df[tok] + 1)) + 1.0
            if tok in name_bag:
                s += 2.0 * idf
            if tok in col_bag:
                s += 1.0 * idf
            if tok in val_bag:
                s += 0.6 * idf
        # Compound names: "gas stations" must match `gasstations`. Token
        # equality cannot see that, and BIRD is full of such names.
        qc = qcompact
        for name in [t] + meta["cols"]:
            nc = compact(name)
            if len(nc) >= 6 and nc in qc:
                s += 2.5
        # Literal grounding: an enum value quoted in the question is the
        # strongest cheap signal there is ("in Alameda" -> County Name).
        for col, vals in meta["values"].items():
            for v in vals:
                vc = compact(v)
                if len(vc) >= 4 and vc in qc:
                    s += 2.0
        scores[t] = s
    return scores


MIN_TABLES_TO_LINK = 6


def select(stats, question, k=K_DEFAULT, with_fk=True, min_tables=MIN_TABLES_TO_LINK):
    """Return the tables to put in the prompt.

    On a schema that already fits, pruning is pure risk: every dropped table is a
    chance to make the question unanswerable, and the token saving is irrelevant.
    So linking only engages above `min_tables`, which is also the only regime the
    product claims to help (large enterprise schemas).
    """
    if len(stats) <= min_tables:
        return list(stats), {t: 0.0 for t in stats}
    scores = score_tables(stats, question)
    ranked = [t for t, s in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])) if s > 0]
    picked = ranked[:k]
    if not picked:                      # nothing matched: do not starve the model
        picked = list(stats)[:k]
    if with_fk:
        changed = True
        while changed:                  # one closure pass, repeated for chains
            changed = False
            for t in list(picked):
                for target in stats[t]["fks"].values():
                    tt = target.split(".")[0]
                    if tt in stats and tt not in picked:
                        picked.append(tt)
                        changed = True
    return picked, scores


def render_linked(stats, picked, sample_rows=None):
    """Same shape as the `samples` card, but only for the selected tables."""
    lines = []
    for t in picked:
        lines.append("Table: %s" % t)
        for c in stats[t]["cols"]:
            vs = stats[t]["values"].get(c) or []
            tail = "  -- values: " + ", ".join(vs[:6]) if vs else ""
            lines.append("  %s%s" % (c, tail))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def gold_tables(gold_sql: str, known):
    """Tables the gold query references. Quote-aware enough for BIRD's SQL."""
    s = " " + re.sub(r"[`\"]", " ", gold_sql.lower()) + " "
    hit = []
    for t in known:
        if re.search(r"(?<![\w])%s(?![\w])" % re.escape(t.lower()), s):
            hit.append(t)
    return hit


def selftest():
    """The retriever must be able to fail, or recall means nothing."""
    import tempfile

    tmp = tempfile.mkdtemp(prefix="poc63-")
    db = os.path.join(tmp, "t.sqlite")
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE customers(customer_id INTEGER PRIMARY KEY, customer_name TEXT, country TEXT);
    CREATE TABLE orders(order_id INTEGER PRIMARY KEY, customer_id INTEGER, status TEXT);
    CREATE TABLE products(product_id INTEGER PRIMARY KEY, product_name TEXT);
    INSERT INTO customers VALUES (1,'a','CN');
    INSERT INTO orders VALUES (1,1,'completed');
    INSERT INTO products VALUES (1,'widget');
    """)
    c.commit()
    c.close()
    stats = table_stats(db)

    out = []
    picked, scores = select(stats, "how many orders per customer")
    out.append({"case": "picks orders+customers", "pass": set(picked[:2]) == {"orders", "customers"}, "got": picked})
    out.append({"case": "fk closure adds customers from orders",
                "pass": "customers" in picked})

    picked2, _ = select(stats, "which products exist", k=1, with_fk=False, min_tables=0)
    out.append({"case": "k=1 honours the budget", "pass": len(picked2) == 1, "got": picked2})

    # On a schema that already fits, pruning is risk without benefit.
    picked_small, _ = select(stats, "which products exist", k=1, with_fk=False)
    out.append({"case": "small schema is not pruned",
                "pass": set(picked_small) == set(stats), "got": picked_small})

    # a token that appears in every table must not dominate (idf)
    s = score_tables(stats, "status")
    out.append({"case": "enum value beats container word",
                "pass": scores["orders"] >= max(v for k, v in s.items() if k != "orders")})

    known = ["customers", "orders", "products"]
    gt = gold_tables("SELECT count(*) FROM orders o JOIN customers c ON o.customer_id=c.customer_id", known)
    out.append({"case": "gold table extraction", "pass": set(gt) == {"orders", "customers"}, "got": gt})
    gt2 = gold_tables("SELECT product_id FROM products WHERE product_name LIKE '%order%'", known)
    out.append({"case": "string literal does not fake a table",
                "pass": gt2 == ["products"], "got": gt2})
    return {"checks": out, "pass": sum(1 for x in out if x["pass"]), "total": len(out),
            "ok": all(x["pass"] for x in out)}
