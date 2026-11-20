"""
POC-30: NL2SQL 基线实测（给 SOTA 计划一个真实起点）
- 5 表零售 schema（BIRD 风格：多表 join / 比率 / 时间分桶 / anti-join / 窗口）
- 30 题，零样本 schema card（含枚举列样例值，POC-8 的结论）
- DeepSeek chat, temperature=0, 3 次取多数
- 指标：EX（多重集）、token 成本、延迟、错误分类
"""
import json, os, time, random, decimal, datetime, re, collections
import duckdb, requests

KEY = os.environ['DEEPSEEK_API_KEY']       # export DEEPSEEK_API_KEY=... before running
URL = 'https://api.deepseek.com/chat/completions'
MODEL = 'deepseek-chat'
RUNS = 3

# ---------------- 数据 ----------------
def build_db():
    con = duckdb.connect()
    con.execute("""
    CREATE TABLE customers(customer_id INT, name VARCHAR, city VARCHAR, segment VARCHAR, signup_date DATE);
    CREATE TABLE products(product_id INT, name VARCHAR, category VARCHAR, brand VARCHAR, cost DECIMAL(10,2));
    CREATE TABLE orders(order_id BIGINT, customer_id INT, order_date DATE, status VARCHAR, channel VARCHAR, total_amount DECIMAL(12,2));
    CREATE TABLE order_items(item_id BIGINT, order_id BIGINT, product_id INT, qty INT, unit_price DECIMAL(12,2), discount DECIMAL(5,2));
    CREATE TABLE refunds(refund_id BIGINT, order_id BIGINT, refund_date DATE, amount DECIMAL(12,2), reason VARCHAR);
    """)
    rnd = random.Random(20261018)
    cities = ['Beijing', 'Shanghai', 'Shenzhen', 'Chengdu', 'Hangzhou']
    segs = ['SMB', 'Enterprise', 'Consumer']
    cats = ['Electronics', 'Apparel', 'Food', 'Home']
    brands = ['Acme', 'Bolt', 'Crest', 'Dune']
    chans = ['web', 'app', 'store']
    reasons = ['damaged', 'wrong_item', 'late', 'changed_mind']
    con.executemany("INSERT INTO customers VALUES (?,?,?,?,?)",
        [(i, f'cust{i:04d}', rnd.choice(cities), rnd.choice(segs),
          datetime.date(2024, 1, 1) + datetime.timedelta(days=rnd.randint(0, 700))) for i in range(1, 201)])
    con.executemany("INSERT INTO products VALUES (?,?,?,?,?)",
        [(i, f'prod{i:03d}', rnd.choice(cats), rnd.choice(brands), decimal.Decimal(rnd.randint(10, 500))) for i in range(1, 101)])
    orders = []
    for i in range(1, 2001):
        d = datetime.date(2025, 1, 1) + datetime.timedelta(days=rnd.randint(0, 500))
        orders.append((i, rnd.randint(1, 200), d, rnd.choices(['paid', 'refunded', 'pending'], [0.8, 0.12, 0.08])[0],
                       rnd.choice(chans), decimal.Decimal(0)))
    con.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", orders)
    items = []
    for i in range(1, 6001):
        oid = rnd.randint(1, 2000)
        items.append((i, oid, rnd.randint(1, 100), rnd.randint(1, 5),
                      decimal.Decimal(rnd.randint(10, 300)), decimal.Decimal(rnd.choice([0, 0, 0.05, 0.1]))))
    con.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", items)
    con.execute("""
      UPDATE orders o SET total_amount = ROUND(s.amt, 2) FROM (
        SELECT order_id, SUM(qty*unit_price*(1-discount)) amt FROM order_items GROUP BY 1) s
      WHERE o.order_id = s.order_id AND o.total_amount = 0
    """)
    refs = []
    for i in range(1, 121):
        oid = rnd.randint(1, 2000)
        refs.append((i, oid, datetime.date(2025, 6, 1) + datetime.timedelta(days=rnd.randint(0, 200)),
                     decimal.Decimal(rnd.randint(10, 400)), rnd.choice(reasons)))
    con.executemany("INSERT INTO refunds VALUES (?,?,?,?,?)", refs)
    return con

SCHEMA_CARD = """Tables:
customers(customer_id INT PK, name VARCHAR, city VARCHAR, segment VARCHAR [SMB|Enterprise|Consumer], signup_date DATE)
products(product_id INT PK, name VARCHAR, category VARCHAR [Electronics|Apparel|Food|Home], brand VARCHAR, cost DECIMAL)
orders(order_id BIGINT PK, customer_id INT FK->customers, order_date DATE, status VARCHAR [paid|refunded|pending], channel VARCHAR [web|app|store], total_amount DECIMAL)
order_items(item_id BIGINT PK, order_id BIGINT FK->orders, product_id INT FK->products, qty INT, unit_price DECIMAL, discount DECIMAL)
refunds(refund_id BIGINT PK, order_id BIGINT FK->orders, refund_date DATE, amount DECIMAL, reason VARCHAR [damaged|wrong_item|late|changed_mind])"""

# ---------------- 题库（30 题） ----------------
Q = [
 ("q01", "How many orders are there in total?", "simple_count",
  "SELECT count(*) FROM orders"),
 ("q02", "What is the total revenue from paid orders?", "simple_sum",
  "SELECT sum(total_amount) FROM orders WHERE status='paid'"),
 ("q03", "How many distinct customers have placed at least one order?", "distinct_count",
  "SELECT count(DISTINCT customer_id) FROM orders"),
 ("q04", "What is the average order amount for paid orders?", "avg",
  "SELECT avg(total_amount) FROM orders WHERE status='paid'"),
 ("q05", "List revenue by city for paid orders.", "join_group",
  "SELECT c.city, sum(o.total_amount) v FROM orders o JOIN customers c USING(customer_id) WHERE o.status='paid' GROUP BY 1"),
 ("q06", "List revenue by product category for paid orders.", "multi_join",
  "SELECT p.category, sum(oi.qty*oi.unit_price*(1-oi.discount)) v FROM orders o JOIN order_items oi USING(order_id) JOIN products p USING(product_id) WHERE o.status='paid' GROUP BY 1"),
 ("q07", "What is the average order value (AOV) by customer segment for paid orders?", "ratio",
  "SELECT c.segment, sum(o.total_amount)/count(DISTINCT o.order_id) v FROM orders o JOIN customers c USING(customer_id) WHERE o.status='paid' GROUP BY 1"),
 ("q08", "Show monthly revenue for paid orders in 2025.", "time_bucket",
  "SELECT strftime(order_date,'%Y-%m') m, sum(total_amount) v FROM orders WHERE status='paid' AND order_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' GROUP BY 1 ORDER BY 1"),
 ("q09", "Which 5 products have the highest total quantity sold?", "topk",
  "SELECT p.name, sum(oi.qty) v FROM order_items oi JOIN products p USING(product_id) GROUP BY 1 ORDER BY 2 DESC LIMIT 5"),
 ("q10", "How many customers have never placed an order?", "anti_join",
  "SELECT count(*) FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id)"),
 ("q11", "What is the refund rate by channel (refunded orders / all orders)?", "ratio_conditional",
  "SELECT channel, count(DISTINCT CASE WHEN status='refunded' THEN order_id END)*1.0/count(DISTINCT order_id) v FROM orders GROUP BY 1"),
 ("q12", "List total refund amount by reason.", "join_group",
  "SELECT reason, sum(amount) v FROM refunds GROUP BY 1"),
 ("q13", "Which city has the highest total refund amount?", "topk_join",
  "SELECT c.city, sum(r.amount) v FROM refunds r JOIN orders o USING(order_id) JOIN customers c USING(customer_id) GROUP BY 1 ORDER BY 2 DESC LIMIT 1"),
 ("q14", "Show the number of orders per month for each channel in 2025.", "time_bucket_multi",
  "SELECT strftime(order_date,'%Y-%m') m, channel, count(*) v FROM orders WHERE order_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' GROUP BY 1,2 ORDER BY 1,2"),
 ("q15", "What is the total gross margin (revenue minus product cost) for paid orders?", "derived",
  "SELECT sum(oi.qty*oi.unit_price*(1-oi.discount)) - sum(oi.qty*p.cost) v FROM orders o JOIN order_items oi USING(order_id) JOIN products p USING(product_id) WHERE o.status='paid'"),
 ("q16", "Which customers have placed more than 10 paid orders?", "having",
  "SELECT c.name, count(*) v FROM orders o JOIN customers c USING(customer_id) WHERE o.status='paid' GROUP BY 1 HAVING count(*) > 10"),
 ("q17", "What is the average discount rate across all order items?", "avg",
  "SELECT avg(discount) FROM order_items"),
 ("q18", "List the top 3 brands by revenue in the Electronics category.", "topk_multi_cond",
  "SELECT p.brand, sum(oi.qty*oi.unit_price*(1-oi.discount)) v FROM order_items oi JOIN products p USING(product_id) JOIN orders o USING(order_id) WHERE o.status='paid' AND p.category='Electronics' GROUP BY 1 ORDER BY 2 DESC LIMIT 3"),
 ("q19", "How many orders were refunded but have no record in the refunds table?", "anti_join_cond",
  "SELECT count(*) FROM orders o WHERE o.status='refunded' AND NOT EXISTS (SELECT 1 FROM refunds r WHERE r.order_id=o.order_id)"),
 ("q20", "What is the median order amount for paid orders?", "median",
  "SELECT median(total_amount) FROM orders WHERE status='paid'"),
 ("q21", "List each segment's share of total paid revenue (as a fraction).", "ratio_total",
  "SELECT c.segment, sum(o.total_amount)/(SELECT sum(total_amount) FROM orders WHERE status='paid') v FROM orders o JOIN customers c USING(customer_id) WHERE o.status='paid' GROUP BY 1"),
 ("q22", "For each category, how many distinct customers bought it?", "distinct_multi_join",
  "SELECT p.category, count(DISTINCT o.customer_id) v FROM orders o JOIN order_items oi USING(order_id) JOIN products p USING(product_id) GROUP BY 1"),
 ("q23", "What is the month-over-month growth rate of paid revenue in 2025?", "window",
  "WITH m AS (SELECT strftime(order_date,'%Y-%m') m, sum(total_amount) v FROM orders WHERE status='paid' AND order_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' GROUP BY 1) SELECT m, (v - lag(v) OVER (ORDER BY m))/lag(v) OVER (ORDER BY m) g FROM m ORDER BY 1"),
 ("q24", "Which product category has the highest average item price?", "topk_avg",
  "SELECT p.category, avg(oi.unit_price) v FROM order_items oi JOIN products p USING(product_id) GROUP BY 1 ORDER BY 2 DESC LIMIT 1"),
 ("q25", "How many orders in 2025 have a total amount greater than 500?", "filter_count",
  "SELECT count(*) FROM orders WHERE total_amount > 500 AND order_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31'"),
 ("q26", "List the number of new customers signed up per quarter in 2024.", "time_bucket_quarter",
  "SELECT quarter(signup_date) q, count(*) v FROM customers WHERE year(signup_date)=2024 GROUP BY 1 ORDER BY 1"),
 ("q27", "What percentage of paid orders used the app channel?", "ratio_cond_simple",
  "SELECT count(CASE WHEN channel='app' THEN 1 END)*1.0/count(*) v FROM orders WHERE status='paid'"),
 ("q28", "List each customer's most recent order date.", "window_group",
  "SELECT customer_id, max(order_date) v FROM orders GROUP BY 1"),
 ("q29", "What is the total quantity sold for products that have never been refunded?", "anti_join_multi",
  "SELECT sum(oi.qty) v FROM order_items oi WHERE NOT EXISTS (SELECT 1 FROM refunds r JOIN orders o USING(order_id) WHERE o.order_id=oi.order_id AND r.amount > 0)"),
 ("q30", "Which three cities have the highest average order value for paid orders?", "topk_ratio",
  "SELECT c.city, sum(o.total_amount)/count(DISTINCT o.order_id) v FROM orders o JOIN customers c USING(customer_id) WHERE o.status='paid' GROUP BY 1 ORDER BY 2 DESC LIMIT 3"),
]

PROMPT = """You are a SQL expert. Translate the question into a single DuckDB SQL query.

{schema}

Rules:
- Output ONLY the SQL, no explanation, no markdown fences.
- Use only the tables/columns above.
- Prefer explicit JOIN ... ON.
- Dates are DATE type; use DATE 'YYYY-MM-DD' literals.

Question: {q}
SQL:"""

# ---------------- 工具 ----------------
def norm(v):
    if isinstance(v, decimal.Decimal): return f'{v.normalize():f}'
    if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
    if isinstance(v, float): return f'{round(v, 6):g}'
    if isinstance(v, bool): return str(v)
    return v

def rows_of(con, sql):
    try:
        r = con.execute(sql).fetchall()
        return [[norm(x) for x in row] for row in r], None
    except Exception as e:
        return None, str(e)[:160]

def multiset(rows):
    return sorted(json.dumps(r, ensure_ascii=False, default=str) for r in rows)

def call(prompt, retries=3):
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": 400}
    last = None
    for _ in range(retries):
        try:
            t0 = time.time()
            r = requests.post(URL, headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'},
                              json=body, timeout=90)
            dt = time.time() - t0
            if r.status_code != 200:
                last = f'HTTP {r.status_code}: {r.text[:120]}'
                time.sleep(2); continue
            j = r.json()
            txt = j['choices'][0]['message']['content']
            u = j.get('usage', {})
            return txt, dt, (u.get('prompt_tokens', 0), u.get('completion_tokens', 0)), None
        except Exception as e:
            last = str(e)[:120]; time.sleep(2)
    return None, 0, (0, 0), last

def clean_sql(t):
    if not t: return ''
    t = t.strip()
    t = re.sub(r'^```(?:sql)?\s*', '', t)
    t = re.sub(r'\s*```$', '', t)
    m = re.search(r'(?is)\b(select|with)\b.*', t)
    t = m.group(0) if m else t
    return t.strip().rstrip(';').strip()

def classify(gold_sql, pred_sql, gold_rows, pred_rows, err):
    if err: return 'exec_error'
    if pred_rows is None: return 'exec_error'
    if multiset(gold_rows) == multiset(pred_rows): return 'correct'
    g, p = gold_sql.lower(), (pred_sql or '').lower()
    if len(pred_rows) == 0: return 'empty_wrong'
    if ('limit' in p.split('order by')[-1]) if 'order by' in p else False: return 'limit_mismatch'
    g_tabs = set(re.findall(r'(?:from|join)\s+([a-z_]+)', g))
    p_tabs = set(re.findall(r'(?:from|join)\s+([a-z_]+)', p))
    if g_tabs != p_tabs: return 'wrong_tables'
    if ('where' in g) != ('where' in p): return 'missing_filter'
    if ('group by' in g) != ('group by' in p): return 'missing_group'
    if len(gold_rows) != len(pred_rows): return 'wrong_grouping'
    return 'wrong_value'

# ---------------- 主流程 ----------------
if __name__ == '__main__':
    con = build_db()
    print(f'data: orders={con.execute("select count(*) from orders").fetchone()[0]} '
          f'items={con.execute("select count(*) from order_items").fetchone()[0]}')

    results = []
    t_start = time.time()
    for qid, qtext, cat, gold in Q:
        gold_rows, gerr = rows_of(con, gold)
        assert gerr is None, (qid, gerr)
        runs = []
        for r_i in range(RUNS):
            txt, dt, tok, err = call(PROMPT.format(schema=SCHEMA_CARD, q=qtext))
            sql = clean_sql(txt)
            rows, e2 = rows_of(con, sql) if sql else (None, 'empty_output')
            runs.append({'sql': sql, 'rows': rows, 'err': e2 or err, 'lat': round(dt, 2), 'tok': tok})
        # 多数：归一化 SQL 字符串
        def key(r):
            return re.sub(r'\s+', ' ', (r['sql'] or '').lower()).strip()
        votes = collections.Counter(key(r) for r in runs if r['rows'] is not None)
        if votes:
            winner_key, n_vote = votes.most_common(1)[0]
            chosen = next(r for r in runs if key(r) == winner_key)
        else:
            chosen = runs[0]; n_vote = 0
        ok = chosen['rows'] is not None and multiset(gold_rows) == multiset(chosen['rows'])
        rec = {'id': qid, 'cat': cat, 'q': qtext, 'ok': ok, 'agree': f'{n_vote}/{RUNS}',
               'gold_rows': len(gold_rows), 'pred_rows': (len(chosen['rows']) if chosen['rows'] is not None else None),
               'err': chosen['err'], 'sql': chosen['sql'], 'gold': gold,
               'lat': round(sum(r['lat'] for r in runs) / RUNS, 2),
               'tok_in': sum(r['tok'][0] for r in runs) // RUNS, 'tok_out': sum(r['tok'][1] for r in runs) // RUNS,
               'runs_ok': sum(1 for r in runs if r['rows'] is not None)}
        rec['cls'] = classify(gold, chosen['sql'], gold_rows, chosen['rows'], chosen['err'])
        results.append(rec)
        print(f"  {qid} {cat:<20} ok={ok} agree={rec['agree']} cls={rec['cls']}")

    n = len(results); corr = sum(1 for r in results if r['ok'])
    ex = corr / n
    classes = collections.Counter(r['cls'] for r in results if not r['ok'])
    by_cat = collections.defaultdict(lambda: [0, 0])
    for r in results:
        by_cat[r['cat']][1] += 1
        if r['ok']: by_cat[r['cat']][0] += 1
    out = {
        'n': n, 'correct': corr, 'EX': round(ex, 4),
        'runs': RUNS, 'model': MODEL,
        'by_cat': {k: {'ok': v[0], 'n': v[1], 'ex': round(v[0] / v[1], 3)} for k, v in sorted(by_cat.items())},
        'error_classes': dict(classes),
        'avg_latency_s': round(sum(r['lat'] for r in results) / n, 2),
        'avg_tokens_in': round(sum(r['tok_in'] for r in results) / n, 1),
        'avg_tokens_out': round(sum(r['tok_out'] for r in results) / n, 1),
        'consistency_3of3': sum(1 for r in results if r['agree'] == '3/3') / n,
        'elapsed_s': round(time.time() - t_start, 1),
        'details': results,
    }
    json.dump(out, open('/tmp/poc30_results.json', 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'details'}, ensure_ascii=False, indent=1))
