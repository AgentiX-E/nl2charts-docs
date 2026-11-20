#!/usr/bin/env python3
# POC-9: Chinese adaptation verification (Section 4.17 claims)
# Part A: Chinese time expressions - deterministic parser ground truth vs LLM direct answer
# Part B: Chinese NL -> SQL on English schema vs pinyin-abbreviated schema (DeepSeek, DuckDB execution match)
import os
import json, time, re, sys
import requests
from datetime import date, timedelta
import calendar

API_KEY = os.environ["DEEPSEEK_API_KEY"]   # export DEEPSEEK_API_KEY=... before running
URL = "https://api.deepseek.com/chat/completions"
TODAY = date(2026, 10, 17)

def llm(messages, temperature=0, n=1, retries=3):
    for attempt in range(retries):
        try:
            r = requests.post(URL, headers={"Authorization": f"Bearer {API_KEY}"},
                json={"model": "deepseek-chat", "messages": messages, "temperature": temperature},
                timeout=120)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  llm retry {attempt+1}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("LLM failed")

# ---------- Part A: time expressions ----------
# Ground truth computed deterministically in Python. Convention stated in prompt.
def gt_prev_month(d):  # full previous calendar month
    first = date(d.year, d.month, 1)
    last_prev = first - timedelta(days=1)
    return date(last_prev.year, last_prev.month, 1), last_prev

def gt_month(d, y, m):
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])

def gt_prev_week(d):  # ISO week Mon..Sun
    monday = d - timedelta(days=d.weekday())
    start = monday - timedelta(days=7)
    return start, start + timedelta(days=6)

def gt_quarter(d, y, q):
    return date(y, 3*q - 2, 1), date(y, 3*q, calendar.monthrange(y, 3*q)[1])

def gt_year(d, y):
    return date(y, 1, 1), date(y, 12, 31)

def gt_ytd(d):
    return date(d.year, 1, 1), d

def gt_last_n_days(d, n):  # trailing n days including today
    return d - timedelta(days=n-1), d

def gt_prev_quarter(d):
    q = (d.month - 1)//3 + 1
    y = d.year
    q -= 1
    if q == 0: q, y = 4, y-1
    return gt_quarter(d, y, q)

def gt_same_month_last_year(d):
    return gt_month(d, d.year - 1, d.month)

def gt_fiscal_ytd(d, fy_start=4):  # fiscal year starts in April
    if d.month >= fy_start:
        return date(d.year, fy_start, 1), d
    return date(d.year - 1, fy_start, 1), d

def gt_last_full_quarter(d):
    q = (d.month - 1)//3  # quarters fully ended before today
    y = d.year
    if q == 0: q, y = 4, y - 1
    return gt_quarter(d, y, q)

def gt_last_full_month(d):
    return gt_prev_month(d)

def gt_same_quarter_last_year(d):
    q = (d.month - 1)//3 + 1
    return gt_quarter(d, d.year - 1, q)

def gt_half_year(d, y, h):
    if h == 1: return date(y,1,1), date(y,6,30)
    return date(y,7,1), date(y,12,31)

EXPRS = [
    ("上个月", lambda: gt_prev_month(TODAY), False),
    ("本月", lambda: gt_month(TODAY, 2026, 10), False),  # convention: 本月 = full current month
    ("上周", lambda: gt_prev_week(TODAY), False),
    ("去年全年", lambda: gt_year(TODAY, 2025), False),
    ("今年以来", lambda: gt_ytd(TODAY), False),
    ("年初至今", lambda: gt_ytd(TODAY), False),
    ("过去30天", lambda: gt_last_n_days(TODAY, 30), False),
    ("最近90天", lambda: gt_last_n_days(TODAY, 90), False),
    ("上个季度", lambda: gt_prev_quarter(TODAY), False),
    ("2025年10月", lambda: gt_month(TODAY, 2025, 10), False),
    ("2024年3月到5月", lambda: (date(2024,3,1), date(2024,5,31)), False),
    ("去年10月", lambda: gt_month(TODAY, 2025, 10), False),
    ("去年第四季度", lambda: gt_quarter(TODAY, 2025, 4), False),
    ("2026年第一季度", lambda: gt_quarter(TODAY, 2026, 1), False),
    ("今年上半年", lambda: gt_half_year(TODAY, 2026, 1), False),
    ("上个月整月", lambda: gt_prev_month(TODAY), False),
    ("上一个完整季度", lambda: gt_last_full_quarter(TODAY), False),
    ("上一个完整月份", lambda: gt_last_full_month(TODAY), False),
    ("去年同期（按月）", lambda: gt_same_month_last_year(TODAY), False),
    ("去年同一季度", lambda: gt_same_quarter_last_year(TODAY), False),
    ("本月截至昨天", lambda: (date(2026,10,1), date(2026,10,16)), False),
    ("昨天", lambda: (date(2026,10,16), date(2026,10,16)), False),
    ("前天", lambda: (date(2026,10,15), date(2026,10,15)), False),
    ("过去一周（含今天）", lambda: gt_last_n_days(TODAY, 7), False),
    ("本季度", lambda: gt_quarter(TODAY, 2026, 4), False),
    ("2025年全年", lambda: gt_year(TODAY, 2025), False),
    ("上上个季度", lambda: gt_quarter(TODAY, 2026, 2), False),
    ("去年一整年", lambda: gt_year(TODAY, 2025), False),
    ("近一年（截至今天）", lambda: (TODAY - timedelta(days=364), TODAY), False),
    ("过去12个月", lambda: (TODAY - timedelta(days=364), TODAY), False),
    # fiscal year start = April, stated in prompt
    ("本财年（财年起始月为4月）", lambda: gt_fiscal_ytd(TODAY, 4), True),
    ("本财年至今（财年起始月为4月）", lambda: gt_fiscal_ytd(TODAY, 4), True),
    ("上一财年（财年起始月为4月）", lambda: (date(2025,4,1), date(2026,3,31)), True),
    ("财年2026（财年起始月为4月）", lambda: (date(2025,4,1), date(2026,3,31)), True),
    ("本财年Q2（财年起始月为4月）", lambda: (date(2026,7,1), date(2026,9,30)), True),
    ("上个财年（财年起始月为4月）", lambda: (date(2025,4,1), date(2026,3,31)), True),
]

def iso(t): return (t[0].isoformat(), t[1].isoformat())

def run_part_a(runs=3):
    prompt = (
        "今天是 2026-10-17（周六）。时间约定：'本月/本季度/本财年'指完整的当前期间（即使尚未结束，也给出该期间的完整起止）；"
        "'过去N天/近N天/最近N天'指含今天的最近N个自然日；财年起始月按题目中括号内的说明。"
        "对每个中文时间表达，给出其对应的日期区间。只输出 JSON 数组，元素形如 "
        '{"expr":"<原表达>","start":"YYYY-MM-DD","end":"YYYY-MM-DD"}，不要输出其他内容。\n\n'
        "时间表达列表：\n" + "\n".join(f"- {e}" for e, _, _ in EXPRS)
    )
    results = []
    for run in range(runs):
        out = llm([{"role": "user", "content": prompt}])
        m = re.search(r"\[.*\]", out, re.S)
        parsed = {}
        if m:
            try:
                arr = json.loads(m.group(0))
                parsed = {a["expr"]: (a["start"], a["end"]) for a in arr if "expr" in a}
            except Exception as e:
                print(f"run{run}: JSON parse fail {e}", file=sys.stderr)
        correct = 0
        for expr, fn, fiscal in EXPRS:
            expect = iso(fn())
            got = parsed.get(expr)
            ok = (got == expect)
            correct += ok
            results.append({"run": run, "expr": expr, "fiscal": fiscal,
                            "expect": list(expect), "got": list(got) if got else None, "ok": ok})
        print(f"Part A run{run}: {correct}/{len(EXPRS)} correct")
    return results

# ---------- Part B: NL -> SQL, English vs pinyin schema ----------
SCHEMA_EN = """
CREATE TABLE orders (order_id BIGINT, user_id BIGINT, region VARCHAR, amount DECIMAL(10,2), status VARCHAR, created_at DATE);
CREATE TABLE users (user_id BIGINT, user_name VARCHAR, city VARCHAR, vip_level INTEGER);
CREATE TABLE products (product_id BIGINT, product_name VARCHAR, category VARCHAR, price DECIMAL(10,2));
CREATE TABLE order_items (item_id BIGINT, order_id BIGINT, product_id BIGINT, quantity INTEGER, unit_price DECIMAL(10,2));
"""
SCHEMA_PINYIN = """
CREATE TABLE dd (ddbh BIGINT, yhbh BIGINT, dq VARCHAR, je DECIMAL(10,2), zt VARCHAR, cjsj DATE);
CREATE TABLE yh (yhbh BIGINT, yhmc VARCHAR, cs VARCHAR, vipdj INTEGER);
CREATE TABLE cp (cpbh BIGINT, cpmc VARCHAR, fl VARCHAR, jg DECIMAL(10,2));
CREATE TABLE ddmx (mxbh BIGINT, ddbh BIGINT, cpbh BIGINT, sl INTEGER, dj DECIMAL(10,2));
"""
COMMENT_PINYIN = """
-- dd: 订单表。ddbh=订单编号, yhbh=用户编号, dq=地区, je=金额, zt=状态(paid已支付/refunded已退款/pending待支付), cjsj=创建日期
-- yh: 用户表。yhbh=用户编号, yhmc=用户名称, cs=城市, vipdj=会员等级(1-3)
-- cp: 商品表。cpbh=商品编号, cpmc=商品名称, fl=品类, jg=单价
-- ddmx: 订单明细表。mxbh=明细编号, ddbh=订单编号, cpbh=商品编号, sl=数量, dj=单价
"""
COMMENT_EN = """
-- orders: orders. order_id, user_id, region, amount, status (paid/refunded/pending), created_at
-- users: users. user_id, user_name, city, vip_level (1-3)
-- products: products. product_id, product_name, category, price
-- order_items: order_items. item_id, order_id, product_id, quantity, unit_price
"""

# 20 questions with gold SQL (on English schema)
QUESTIONS = [
    ("2026年9月各地区的已支付订单总金额是多少？", "SELECT region, SUM(amount) AS total FROM orders WHERE status='paid' AND created_at >= '2026-09-01' AND created_at <= '2026-09-30' GROUP BY region ORDER BY total DESC"),
    ("哪个城市的VIP3级用户最多？", "SELECT u.city, COUNT(*) AS cnt FROM users u WHERE u.vip_level=3 GROUP BY u.city ORDER BY cnt DESC LIMIT 1"),
    ("订单金额最高的前5笔订单及其用户城市", "SELECT o.order_id, o.amount, u.city FROM orders o JOIN users u ON o.user_id=u.user_id ORDER BY o.amount DESC LIMIT 5"),
    ("已支付订单的平均金额是多少？", "SELECT AVG(amount) FROM orders WHERE status='paid'"),
    ("各订单状态的订单数分别是多少？", "SELECT status, COUNT(*) FROM orders GROUP BY status"),
    ("销售额最高的品类是哪个？（仅已支付订单）", "SELECT p.category, SUM(oi.quantity*oi.unit_price) AS gmv FROM order_items oi JOIN orders o ON oi.order_id=o.order_id JOIN products p ON oi.product_id=p.product_id WHERE o.status='paid' GROUP BY p.category ORDER BY gmv DESC LIMIT 1"),
    ("2026年10月每天的订单数量趋势", "SELECT created_at, COUNT(*) FROM orders WHERE created_at >= '2026-10-01' GROUP BY created_at ORDER BY created_at"),
    ("北京的用户一共有多少笔已支付订单？", "SELECT COUNT(*) FROM orders o JOIN users u ON o.user_id=u.user_id WHERE u.city='北京' AND o.status='paid'"),
    ("每个地区的用户数量", "SELECT city, COUNT(*) FROM users GROUP BY city"),
    ("价格高于100的商品有哪些？", "SELECT product_name, price FROM products WHERE price > 100"),
    ("被退款的订单总金额", "SELECT SUM(amount) FROM orders WHERE status='refunded'"),
    ("VIP等级为1的用户占比是多少？", "SELECT AVG(CASE WHEN vip_level=1 THEN 1.0 ELSE 0.0 END) FROM users"),
    ("销量前3的商品", "SELECT p.product_name, SUM(oi.quantity) AS qty FROM order_items oi JOIN products p ON oi.product_id=p.product_id GROUP BY p.product_name ORDER BY qty DESC LIMIT 3"),
    ("2026年9月和10月各有多少已支付订单？", "SELECT strftime(created_at, '%Y-%m') AS ym, COUNT(*) FROM orders WHERE status='paid' AND created_at >= '2026-09-01' GROUP BY ym"),
    ("订单数量最多的前3个地区", "SELECT region, COUNT(*) FROM orders GROUP BY region ORDER BY 2 DESC LIMIT 3"),
    ("哪些用户下过不止1笔订单？", "SELECT user_id, COUNT(*) FROM orders GROUP BY user_id HAVING COUNT(*) > 1"),
    ("订单明细中平均每单包含几件商品？", "SELECT AVG(cnt) FROM (SELECT order_id, SUM(quantity) AS cnt FROM order_items GROUP BY order_id) t"),
    ("数量超过5件的订单明细有多少条？", "SELECT COUNT(*) FROM order_items WHERE quantity > 5"),
    ("各会员等级的平均客单价（仅已支付）", "SELECT u.vip_level, AVG(o.amount) FROM orders o JOIN users u ON o.user_id=u.user_id WHERE o.status='paid' GROUP BY u.vip_level"),
    ("最晚一笔订单是什么时候？", "SELECT MAX(created_at) FROM orders"),
]

import duckdb
def make_db(schema):
    con = duckdb.connect()
    con.execute(schema)
    t = re.findall(r"CREATE TABLE (\w+)", schema)
    tbl_orders, tbl_users, tbl_products, tbl_items = t[0], t[1], t[2], t[3]
    import random
    random.seed(42)
    regions = ["华东","华北","华南","西南"]; cities = ["北京","上海","深圳","成都"]
    rows = [(i, random.randint(1,50), random.choice(regions), round(random.uniform(20,2000),2),
             random.choice(["paid"]*6+["refunded","pending"]), date(2026, random.randint(9,10), random.randint(1,28))) for i in range(1,301)]
    con.executemany(f"INSERT INTO {tbl_orders} VALUES (?,?,?,?,?,?)", rows)
    con.executemany(f"INSERT INTO {tbl_users} VALUES (?,?,?,?)", [(i, f"u{i}", random.choice(cities), random.randint(1,3)) for i in range(1,51)])
    con.executemany(f"INSERT INTO {tbl_products} VALUES (?,?,?,?)", [(i, f"P{i}", random.choice(["数码","服饰","食品","家居"]), round(random.uniform(10,500),2)) for i in range(1,31)])
    items = []
    for i in range(1, 600):
        items.append((i, random.randint(1,300), random.randint(1,30), random.randint(1,8), round(random.uniform(10,300),2)))
    con.executemany(f"INSERT INTO {tbl_items} VALUES (?,?,?,?,?)", items)
    return con

def gold_rows(con, sql):
    return [tuple(r) for r in con.execute(sql).fetchall()]

def rows_compatible(a, b):
    if a is None or b is None: return False
    if len(a) != len(b): return False
    def norm(r): return tuple(round(float(x),2) if isinstance(x,(int,float)) else str(x) for x in r)
    na, nb = sorted(norm(r) for r in a), sorted(norm(r) for r in b)
    # allow top-K ordering differences: compare as multiset
    return na == nb

def run_part_b():
    con = make_db(SCHEMA_EN)
    golds = []
    for q, sql in QUESTIONS:
        try: golds.append(gold_rows(con, sql))
        except Exception as e:
            print(f"gold fail: {q}: {e}", file=sys.stderr); golds.append(None)

    def build_prompt(schema, comments):
        return (
            "你是资深数据分析师。以下是 DuckDB 数据库的 schema 和注释：\n" + schema + comments +
            "\n规则：只输出一条可执行的 SQL（duckdb 方言），放在 ```sql 代码块中，不要任何解释。\n"
        )

    variants = {
        "english": (SCHEMA_EN, COMMENT_EN, SCHEMA_EN),
        "pinyin":  (SCHEMA_PINYIN, COMMENT_PINYIN, SCHEMA_EN),  # gold SQL written on EN schema, exec both on equivalent data? No:
    }
    # For pinyin variant, create an identical dataset but with pinyin table names; gold rows come from the EN db.
    con_pin = make_db(SCHEMA_PINYIN)

    out = []
    for name, (schema, comments, _) in variants.items():
        target_con = con if name == "english" else con_pin
        correct = 0; errs = []
        for (q, sql), gold in zip(QUESTIONS, golds):
            resp = llm([{"role": "user", "content": build_prompt(schema, comments) + "问题：" + q}])
            m = re.search(r"```sql\s*(.*?)```", resp, re.S) or re.search(r"(SELECT.*)", resp, re.S|re.I)
            got_rows = None; sql_txt = None
            if m:
                sql_txt = m.group(1).strip()
                try: got_rows = gold_rows(target_con, sql_txt)
                except Exception as e: errs.append({"q": q, "error": str(e)[:120]})
            ok = rows_compatible(gold, got_rows)
            correct += ok
            out.append({"variant": name, "q": q, "ok": ok, "sql": sql_txt, "error": (errs[-1]["error"] if errs and errs[-1]["q"]==q else None),
                        "got": [list(map(str,r)) for r in (got_rows or [])][:5], "gold": [list(map(str,r)) for r in (gold or [])][:5]})
        print(f"Part B [{name}]: {correct}/{len(QUESTIONS)}")
    return out

if __name__ == "__main__":
    import os
    t0 = time.time()
    a = run_part_a(runs=3) if not os.path.exists("/tmp/poc9_a.json") else json.load(open("/tmp/poc9_a.json"))
    if not os.path.exists("/tmp/poc9_a.json"): json.dump(a, open("/tmp/poc9_a.json","w"), ensure_ascii=False)
    b = run_part_b()
    json.dump({"partA": a, "partB": b}, open("/tmp/poc9_results.json", "w"), ensure_ascii=False, indent=1)
    # summary
    for run in range(3):
        rs = [r for r in a if r["run"] == run]
        print(f"A run{run}: {sum(r['ok'] for r in rs)}/{len(rs)}  fiscal: {sum(r['ok'] for r in rs if r['fiscal'])}/{sum(1 for r in rs if r['fiscal'])}  non-fiscal: {sum(r['ok'] for r in rs if not r['fiscal'])}/{sum(1 for r in rs if not r['fiscal'])}")
    for v in ["english", "pinyin"]:
        rs = [r for r in b if r["variant"] == v]
        print(f"B {v}: {sum(r['ok'] for r in rs)}/{len(rs)}")
    print(f"total {time.time()-t0:.0f}s")
