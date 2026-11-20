#!/usr/bin/env python3
"""POC-12 fixture: both sides of the federation, in one versioned file.

The CI job used to seed `orders(id, region, amount, status, created_at)` and a
SQLite `region_dim(id, owner)`, while main.js joins on `region_id`, reads
`payload/uid/tags`, and joins a SQLite table called `t`. The two drifted apart,
so the step failed on a missing column long before it could say anything about
federation. Keeping the fixture next to the script is the only way that stays
true.

PostgreSQL connection comes from the standard env vars (PGHOST, PGUSER,
PGPASSWORD, PGDATABASE), defaulting to the values the workflow uses.
"""
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PG = dict(
    host=os.environ.get("PGHOST", "127.0.0.1"),
    user=os.environ.get("PGUSER", "t2c"),
    db=os.environ.get("PGDATABASE", "analytics"),
)

PG_SQL = """
DROP TABLE IF EXISTS orders;
CREATE TABLE orders(
  id bigint primary key,
  region_id int,
  amount numeric(12,2),
  status text,
  created_at timestamptz default now(),
  payload text,
  uid uuid,
  tags text[]
);
INSERT INTO orders(id, region_id, amount, status, created_at, payload, uid, tags)
SELECT i, 1 + i % 3, (i * 7 % 1000) / 10.0,
       CASE WHEN i % 4 = 0 THEN 'open' ELSE 'paid' END,
       now() - (i || ' hours')::interval,
       '{"k":' || i || '}',
       gen_random_uuid(),
       ARRAY['a','b']
FROM generate_series(1, 50000) i;
DROP TABLE IF EXISTS dim_region;
CREATE TABLE dim_region(region_id int primary key, region_name text);
INSERT INTO dim_region VALUES (1,'north'),(2,'south'),(3,'east');
ANALYZE orders;
"""


def pg(sql: str) -> None:
    env = dict(os.environ, PGPASSWORD=os.environ.get("PGPASSWORD", "t2cpass"))
    r = subprocess.run(
        ["psql", "-h", PG["host"], "-U", PG["user"], "-d", PG["db"],
         "-v", "ON_ERROR_STOP=1", "-q", "-c", sql],
        env=env, capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit("psql failed: %s" % (r.stderr.strip()[:300]))


def sqlite_side() -> None:
    db = os.path.join(HERE, "small.sqlite")
    con = sqlite3.connect(db)
    con.executescript("""
    DROP TABLE IF EXISTS t;
    CREATE TABLE t (k TEXT, region_id INT);
    INSERT INTO t VALUES ('a', 1), ('b', 2), ('c', 3);
    """)
    con.commit()
    con.close()


if __name__ == "__main__":
    pg(PG_SQL)
    sqlite_side()
    print("fixture ok: pg orders=50000 dim_region=3, sqlite t=3")
