#!/usr/bin/env python3
# POC-18: self-healing loop - which failures are actually repairable within 2 retries?
import os
import json, re, time, requests, duckdb, random
from datetime import date, timedelta

API_KEY = os.environ["DEEPSEEK_API_KEY"]   # export DEEPSEEK_API_KEY=... before running
URL = "https://api.deepseek.com/chat/completions"

def llm(messages, temperature=0, retries=3):
    for k in range(retries):
        try:
            r = requests.post(URL, headers={"Authorization": f"Bearer {API_KEY}"},
                json={"model": "deepseek-chat", "messages": messages, "temperature": temperature}, timeout=120)
            r.raise_for_status()
            j = r.json()
            return j["choices"][0]["message"]["content"], j.get("usage", {})
        except Exception as e:
            print("retry", k, e); time.sleep(2*(k+1))
    raise RuntimeError("llm failed")

# ---------- dataset ----------
con = duckdb.connect()
random.seed(3)
con.execute("""
CREATE TABLE regions(region_id INT, region_name VARCHAR);
CREATE TABLE users(user_id INT, user_name VARCHAR, city VARCHAR, vip_level INT);
CREATE TABLE products(product_id INT, product_name VARCHAR, category VARCHAR, price DECIMAL(10,2));
CREATE TABLE orders(order_id BIGINT, user_id INT, region_id INT, amount DECIMAL(12,2), status VARCHAR, created_at DATE);
CREATE TABLE order_items(order_id BIGINT, product_id INT, qty INT, unit_price DECIMAL(12,2));
""")
con.executemany("INSERT INTO regions VALUES (?,?)", [(i, f"大区{i}") for i in range(1,5)])
con.executemany("INSERT INTO users VALUES (?,?,?,?)", [(i, f"用户{i}", random.choice(["北京","上海","深圳"]), random.randint(1,3)) for i in range(1,51)])
con.executemany("INSERT INTO products VALUES (?,?,?,?)", [(i, f"商品{i}", random.choice(["数码","服饰","食品"]), round(random.uniform(10,500),2)) for i in range(1,31)])
orders=[]; items=[]
for oid in range(1, 601):
    d = date(2026,1,1)+timedelta(days=oid % 120)
    orders.append((oid, random.randint(1,50), random.randint(1,4), round(random.uniform(50,3000),2), random.choice(["paid"]*7+["refunded","pending"]), d))
    for _ in range(random.randint(1,3)):
        items.append((oid, random.randint(1,30), random.randint(1,4), round(random.uniform(10,400),2)))
con.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", orders)
con.executemany("INSERT INTO order_items VALUES (?,?,?,?)", items)

SCHEMA = """表结构（DuckDB）：
regions(region_id INT, region_name VARCHAR)  -- 大区
users(user_id INT, user_name VARCHAR, city VARCHAR, vip_level INT)  -- 用户；vip_level 1-3
products(product_id INT, product_name VARCHAR, category VARCHAR, price DECIMAL(10,2))  -- 商品
orders(order_id BIGINT, user_id INT, region_id INT, amount DECIMAL(12,2), status VARCHAR, created_at DATE)  -- 订单；status: paid/refunded/pending
order_items(order_id BIGINT, product_id INT, qty INT, unit_price DECIMAL(12,2))  -- 订单明细
"""

# (name, question, gold_sql, broken_sql, error_class, expected_error?)
CASES = [
 ("typo_column","2026年9月已支付订单的总金额","SELECT sum(amount) FROM orders WHERE status='paid' AND created_at BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'",
  "SELECT sum(amout) FROM orders WHERE status='paid' AND created_at BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'","unknown_column"),
 ("unknown_table","每个大区的订单数","SELECT region_id, count(*) FROM orders GROUP BY 1 ORDER BY 1",
  "SELECT region_id, count(*) FROM order GROUP BY 1 ORDER BY 1","unknown_table"),
 ("type_mismatch","已支付订单按状态计数","SELECT status, count(*) FROM orders WHERE status='paid' GROUP BY 1",
  "SELECT status, count(*) FROM orders WHERE status = 1 GROUP BY 1","type_mismatch"),
 ("wrong_agg","每个品类的总销售额","SELECT p.category, sum(oi.qty*oi.unit_price) FROM order_items oi JOIN products p USING(product_id) GROUP BY 1 ORDER BY 1",
  "SELECT p.category, sum(p.product_name) FROM order_items oi JOIN products p USING(product_id) GROUP BY 1 ORDER BY 1","wrong_aggregation"),
 ("missing_group","各城市用户数","SELECT city, count(*) FROM users GROUP BY 1 ORDER BY 1",
  "SELECT city, count(*) FROM users","missing_group_by"),
 ("bad_join","每个大区的销售额","SELECT r.region_name, sum(o.amount) FROM orders o JOIN regions r USING(region_id) WHERE o.status='paid' GROUP BY 1 ORDER BY 1",
  "SELECT r.region_name, sum(o.amount) FROM orders o JOIN regions r ON o.user_id = r.region_id WHERE o.status='paid' GROUP BY 1 ORDER BY 1","wrong_join_key"),
 ("syntax","VIP3 用户数","SELECT count(*) FROM users WHERE vip_level = 3",
  "SELECT count(*) FORM users WHERE vip_level = 3","syntax_error"),
 ("func_missing","订单日期按月汇总","SELECT strftime(created_at,'%Y-%m') m, count(*) FROM orders GROUP BY 1 ORDER BY 1",
  "SELECT date_format(created_at,'%Y-%m') m, count(*) FROM orders GROUP BY 1 ORDER BY 1","function_not_found"),
 ("date_literal","2026年10月1日之后的订单数","SELECT count(*) FROM orders WHERE created_at >= DATE '2026-10-01'",
  "SELECT count(*) FROM orders WHERE created_at >= '2026/10/01'","date_format_error"),
 ("ambiguous","按大区统计销售额","SELECT r.region_name, sum(o.amount) FROM orders o JOIN regions r USING(region_id) WHERE o.status='paid' GROUP BY 1 ORDER BY 1",
  "SELECT region_name, sum(amount) FROM orders JOIN regions USING(region_id) WHERE status='paid' GROUP BY 1 ORDER BY 1","ambiguous_column"),
 # semantic errors: run fine but wrong -> self-heal cannot see them
 ("silent_missing_filter","已支付订单的销售额","SELECT sum(amount) FROM orders WHERE status='paid'",
  "SELECT sum(amount) FROM orders","silent_wrong"),
 ("silent_wrong_grain","每笔订单的平均商品件数","SELECT avg(cnt) FROM (SELECT order_id, sum(qty) cnt FROM order_items GROUP BY 1) t",
  "SELECT avg(qty) FROM order_items","silent_wrong"),
]

def run_sql(sql):
    try:
        rows = con.execute(sql).fetchall()
        return True, rows, None
    except Exception as e:
        return False, None, str(e).split("\n")[0]

def norm(rows):
    out=[]
    for r in rows:
        out.append(tuple(round(float(x),2) if isinstance(x,(int,float)) else str(x) for x in r))
    return out

def same(a,b):
    try:
        return sorted(norm(a)) == sorted(norm(b))
    except Exception:
        return False

SYSTEM = "你是 SQL 修复器。只输出一条 DuckDB SQL，放在 ```sql 代码块中，不要解释。"

def repair(question, bad_sql, err, with_schema, history):
    ctx = SCHEMA if with_schema else "（无 schema 信息）"
    msg = f"{ctx}\n问题：{question}\n失败的 SQL：\n{bad_sql}\n数据库报错：{err}\n请修复。"
    if history:
        msg += "\n\n之前已尝试过：\n" + "\n---\n".join(history)
    out, usage = llm([{"role":"system","content":SYSTEM},{"role":"user","content":msg}])
    m = re.search(r"```sql\s*(.*?)```", out, re.S) or re.search(r"(SELECT.*)", out, re.S|re.I)
    return (m.group(1).strip() if m else out.strip()), usage

def evaluate(with_schema):
    stats = []
    for name, q, gold, broken, cls in CASES:
        ok0, rows0, err0 = run_sql(broken)
        gold_rows = con.execute(gold).fetchall()
        # if it already runs, self-heal never triggers; record silent wrong
        if ok0:
            entry = dict(case=name, cls=cls, attempt0="runs", correct=same(rows0, gold_rows),
                         healed=None, attempts=0, tokens=0)
            stats.append(entry); continue
        history=[]; healed=False; attempts=0; tokens=0; cur=broken; err=err0
        while attempts < 2 and not healed:
            attempts += 1
            new_sql, usage = repair(q, cur, err, with_schema, history)
            tokens += usage.get("total_tokens", 0)
            ok, rows, e = run_sql(new_sql)
            if ok and same(rows, gold_rows):
                healed = True; break
            history.append(new_sql)
            cur, err = new_sql, (e or "结果不正确（行集与预期不符）")
        stats.append(dict(case=name, cls=cls, attempt0="error", healed=healed, attempts=attempts, tokens=tokens))
    return stats

print("=== arm A: error only ===")
A = evaluate(False)
print("=== arm B: error + schema ===")
B = evaluate(True)

def summarize(stats, label):
    healed = sum(1 for s in stats if s.get("healed"))
    errs = sum(1 for s in stats if s["attempt0"] == "error")
    silent = [s for s in stats if s["attempt0"] == "runs"]
    silent_wrong = [s for s in silent if not s["correct"]]
    print(f"[{label}] repairable {healed}/{errs} | silent-wrong {len(silent_wrong)}/{len(silent)} | avg tokens {sum(s['tokens'] for s in stats)/max(1,errs):.0f}")
    for s in stats:
        print("  ", s["case"], s["cls"], "healed" if s.get("healed") else ("runs-correct" if s.get("correct") else "unresolved"), s.get("attempts"))
summarize(A,"A error-only"); summarize(B,"B +schema")
json.dump({"A":A,"B":B}, open('/tmp/poc18_results.json','w'), ensure_ascii=False, indent=1)
