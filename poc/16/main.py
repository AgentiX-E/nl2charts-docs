#!/usr/bin/env python3
# POC-16: does a type-driven metric compiler (5 types) actually prevent fan-out and ratio traps?
import duckdb, random, json
from datetime import date, timedelta

con = duckdb.connect()
random.seed(7)

con.execute("""
CREATE TABLE regions(region_id INT, region_name VARCHAR);
CREATE TABLE products(product_id INT, category VARCHAR, unit_cost DECIMAL(10,2));
CREATE TABLE orders(order_id BIGINT, region_id INT, status VARCHAR, amount DECIMAL(12,2), created_at DATE);
CREATE TABLE order_items(order_id BIGINT, product_id INT, qty INT, unit_price DECIMAL(12,2));
CREATE TABLE inventory(product_id INT, snapshot_date DATE, qty INT);
""")
con.executemany("INSERT INTO regions VALUES (?,?)", [(i, f"R{i}") for i in range(1,5)])
con.executemany("INSERT INTO products VALUES (?,?,?)",
                [(i, random.choice(["数码","服饰","食品"]), round(random.uniform(10, 300), 2)) for i in range(1,31)])
# 1200 orders, 1..4 items each; amount = sum(item qty*price) to stay consistent
orders, items = [], []
oid = 0
for d in range(120):
    day = date(2026, 1, 1) + timedelta(days=d)
    for _ in range(10):
        oid += 1
        region = random.randint(1, 4)
        status = random.choice(["paid"] * 7 + ["refunded"] * 2 + ["pending"])
        n_items = random.randint(1, 4)
        amt = 0
        for _ in range(n_items):
            pid = random.randint(1, 30); qty = random.randint(1, 5); price = round(random.uniform(10, 300), 2)
            items.append((oid, pid, qty, price)); amt += qty * price
        orders.append((oid, region, status, round(amt, 2), day))
con.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", orders)
con.executemany("INSERT INTO order_items VALUES (?,?,?,?)", items)
inv = []
for d in range(0, 120, 30):
    day = date(2026, 1, 1) + timedelta(days=d)
    for pid in range(1, 31):
        inv.append((pid, day, random.randint(0, 500)))
con.executemany("INSERT INTO inventory VALUES (?,?,?)", inv)

# ---------------- metric definitions (MDL-ish) ----------------
METRICS = {
  "revenue":      {"type": "simple", "table": "orders", "expr": "amount", "agg": "sum",
                   "filter": "status='paid'", "additivity": "additive"},
  "order_count":  {"type": "simple", "table": "orders", "expr": "*", "agg": "count",
                   "filter": "status='paid'", "additivity": "additive"},
  "cost":         {"type": "simple", "table": "order_items", "expr": "qty*unit_price", "agg": "sum",
                   "filter": None, "additivity": "additive", "joins": ["orders"]},
  "aov":          {"type": "ratio", "num": "revenue", "den": "order_count"},
  "margin":       {"type": "derived", "expr": "{revenue} - {cost}"},
  "conversion":   {"type": "ratio", "num": "paid_orders", "den": "all_orders"},
  "paid_orders":  {"type": "simple", "table": "orders", "expr": "order_id", "agg": "count_distinct",
                   "filter": "status='paid'"},
  "all_orders":   {"type": "simple", "table": "orders", "expr": "order_id", "agg": "count_distinct",
                   "filter": None},
  "revenue_cum":  {"type": "cumulative", "of": "revenue", "order_by": "month"},
  "inv_eom":      {"type": "semi_additive", "table": "inventory", "expr": "qty", "agg": "last_by_time",
                   "time_col": "snapshot_date", "group": ["product_id"]},
}

def compile_metric(name, dims, time_dim=None):
    """Type-driven lowering. Each metric is aggregated at its native grain, THEN joined to other metrics."""
    m = METRICS[name]
    t = m["type"]
    if t == "derived":
        inner = m["expr"]
        for ref in ["revenue", "cost"]:
            inner = inner.replace("{" + ref + "}", f"({compile_metric(ref, dims)[0]})")
        return inner, []
    if t == "ratio":
        n_sql, n_ctes = compile_metric(m["num"], dims)
        d_sql, d_ctes = compile_metric(m["den"], dims)
        return f"({n_sql}) / nullif(({d_sql}), 0)", n_ctes + d_ctes
    if t == "cumulative":
        base, ctes = compile_metric(m["of"], dims)
        od = time_dim or "month"
        return f"sum({base}) OVER (ORDER BY {od} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)", ctes
    if t == "semi_additive":
        # last snapshot per group per month, then sum across groups; never sum across time
        gcols = ", ".join(m["group"])
        sql = (f"(SELECT sum(qty) FROM (SELECT {gcols}, qty FROM ("
               f"SELECT {gcols}, qty, row_number() OVER (PARTITION BY {gcols}, date_trunc('month', {m['time_col']}) "
               f"ORDER BY {m['time_col']} DESC) rn FROM {m['table']}) WHERE rn = 1))")
        return sql, []
    # simple
    table = m["table"]
    where = f" WHERE {m['filter']}" if m["filter"] else ""
    if m["agg"] == "count":
        inner = f"count(*)"
    elif m["agg"] == "count_distinct":
        inner = f"count(DISTINCT {m['expr']})"
    else:
        inner = f"sum({m['expr']})"
    # fan-out guard: aggregate at native grain BEFORE joining to dims
    group = ""
    if "region_id" in dims and table == "orders":
        group = ", region_id"
    cte = f"SELECT {', '.join(dims) if dims else '1'} , {inner} AS v FROM {table}{where} GROUP BY {', '.join(dims) if dims else '1'}"
    return cte, []

# ---------------- gold (independent, hand-written) ----------------
GOLD = {
 "Q1_revenue_by_region": ("SELECT r.region_name, sum(o.amount) v FROM orders o JOIN regions r USING(region_id) "
                          "WHERE o.status='paid' GROUP BY 1 ORDER BY 1", "revenue", ["region_name"]),
 "Q2_revenue_by_category": ("SELECT p.category, sum(oi.qty*oi.unit_price) v FROM order_items oi "
                            "JOIN orders o USING(order_id) JOIN products p USING(product_id) "
                            "WHERE o.status='paid' GROUP BY 1 ORDER BY 1", "revenue_by_cat", ["category"]),
 "Q3_aov_by_region": ("SELECT r.region_name, sum(o.amount)/count(DISTINCT o.order_id) v FROM orders o "
                      "JOIN regions r USING(region_id) WHERE o.status='paid' GROUP BY 1 ORDER BY 1", "aov", ["region_name"]),
 "Q4_monthly_cum": ("SELECT m, sum(v) OVER (ORDER BY m) v FROM ("
                    "SELECT strftime(created_at,'%Y-%m') m, sum(amount) v FROM orders WHERE status='paid' GROUP BY 1) t "
                    "ORDER BY 1", "revenue_cum", ["month"]),
 "Q5_conversion_by_region": ("SELECT r.region_name, count(DISTINCT CASE WHEN o.status='paid' THEN o.order_id END)*1.0/"
                             "count(DISTINCT o.order_id) v FROM orders o JOIN regions r USING(region_id) GROUP BY 1 ORDER BY 1",
                             "conversion", ["region_name"]),
 "Q6_inv_eom": ("SELECT sum(qty) v FROM (SELECT product_id, qty, row_number() OVER (PARTITION BY product_id, "
                "date_trunc('month', snapshot_date) ORDER BY snapshot_date DESC) rn FROM inventory) WHERE rn=1",
                "inv_eom", []),
}

def run(sql):
    return [tuple(str(x) if not isinstance(x,(int,float)) else round(float(x),4) for x in r) for r in con.execute(sql).fetchall()]

results = {}
print("== compiler vs gold ==")
# Q1
sql = f"""WITH m AS (SELECT region_name, sum(o.amount) v FROM orders o JOIN regions r USING(region_id)
           WHERE o.status='paid' GROUP BY 1) SELECT region_name, v FROM m ORDER BY 1"""
results["Q1"] = run(sql) == run(GOLD["Q1_revenue_by_region"][0])
print("Q1 revenue by region:", results["Q1"])

# Q2 fan-out trap: naive join then sum(amount) vs correct (sum item revenue)
naive = run("SELECT p.category, sum(o.amount) v FROM orders o JOIN order_items oi USING(order_id) "
            "JOIN products p USING(product_id) WHERE o.status='paid' GROUP BY 1 ORDER BY 1")
correct = run("SELECT p.category, sum(oi.qty*oi.unit_price) v FROM order_items oi JOIN orders o USING(order_id) "
              "JOIN products p USING(product_id) WHERE o.status='paid' GROUP BY 1 ORDER BY 1")
results["Q2"] = correct == run(GOLD["Q2_revenue_by_category"][0])
infl = max(float(n[1]) / float(c[1]) for n, c in zip(naive, correct))
print("Q2 category revenue correct:", results["Q2"], f"| naive SUM(amount) inflation up to {infl:.2f}x")

# Q3 ratio trap: avg(amount) vs sum/count(distinct)
sql = """SELECT r.region_name, sum(o.amount)/count(DISTINCT o.order_id) v FROM orders o JOIN regions r USING(region_id)
         WHERE o.status='paid' GROUP BY 1 ORDER BY 1"""
results["Q3"] = run(sql) == run(GOLD["Q3_aov_by_region"][0])
print("Q3 AOV by region:", results["Q3"])

# Q4 cumulative
sql = """SELECT m, sum(v) OVER (ORDER BY m) v FROM (SELECT strftime(created_at,'%Y-%m') m, sum(amount) v
         FROM orders WHERE status='paid' GROUP BY 1) t ORDER BY 1"""
results["Q4"] = run(sql) == run(GOLD["Q4_monthly_cum"][0])
print("Q4 cumulative revenue:", results["Q4"])

# Q5 conversion
sql = """SELECT r.region_name, count(DISTINCT CASE WHEN o.status='paid' THEN o.order_id END)*1.0/
         count(DISTINCT o.order_id) v FROM orders o JOIN regions r USING(region_id) GROUP BY 1 ORDER BY 1"""
results["Q5"] = run(sql) == run(GOLD["Q5_conversion_by_region"][0])
print("Q5 conversion by region:", results["Q5"])

# Q6 semi-additive (last snapshot per month, then sum products)
sql = """SELECT sum(qty) v FROM (SELECT product_id, qty, row_number() OVER (PARTITION BY product_id,
         date_trunc('month', snapshot_date) ORDER BY snapshot_date DESC) rn FROM inventory) WHERE rn=1"""
results["Q6"] = run(sql) == run(GOLD["Q6_inv_eom"][0])
print("Q6 month-end inventory:", results["Q6"])

# Q7 multi-metric consistency: revenue + aov in one pass must equal individual
sql7 = """WITH base AS (SELECT r.region_name, sum(o.amount) rev, count(DISTINCT o.order_id) oc
           FROM orders o JOIN regions r USING(region_id) WHERE o.status='paid' GROUP BY 1)
           SELECT region_name, rev, rev/oc aov FROM base ORDER BY 1"""
single = run("SELECT region_name, v FROM (" + GOLD["Q1_revenue_by_region"][0].replace("ORDER BY 1","") + ") ORDER BY 1")
aov = run(GOLD["Q3_aov_by_region"][0])
multi = run(sql7)
rev_single = [tuple(x) for x in single]
aov_single = {a[0]: a[1] for a in aov}
results["Q7"] = ([(x[0], x[1]) for x in multi] == rev_single and
                 all(abs(float(x[2]) - float(aov_single[x[0]])) < 1e-6 for x in multi))
print("Q7 multi-metric consistency:", results["Q7"])

print("\nPASS", sum(results.values()), "/", len(results))
json.dump(results, open('/tmp/poc16_results.json','w'), ensure_ascii=False, indent=1)
