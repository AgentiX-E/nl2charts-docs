"""
POC-29: ASSERT 三级的误报率 / 漏报率
A1 空结果   ：rows == 0 -> 拦截
A2 grain    ：实体级查询出现重复实体键 -> 拦截
A3 不变量   ：对 non_additive 指标做 SUM/AVG；同一指标换问法行集哈希不一致 -> 拦截

样本：30 条查询
 - 20 条正确（其中 3 条"合法空集"——确实没有数据，这是 A1 的天然误报源）
 - 10 条缺陷（3 静默语义错、2 空集错、2 grain 错、2 不变量错、1 重复行）
"""
import duckdb, json, hashlib

con = duckdb.connect()
con.execute("""
CREATE TABLE orders(order_id BIGINT, user_id INT, region VARCHAR, amount DECIMAL(12,2), status VARCHAR, created_at DATE);
CREATE TABLE items(order_id BIGINT, product_id INT, qty INT, unit_price DECIMAL(12,2));
CREATE TABLE products(product_id INT, category VARCHAR);
""")
import random
random.seed(7)
regions = ['华东','华北','华南','西南']
cats = ['数码','服饰','食品']
con.execute("INSERT INTO products SELECT g, (ARRAY['数码','服饰','食品'])[1+(g%3)] FROM (SELECT unnest(generate_series(1,30)) AS g)")
con.execute("INSERT INTO orders SELECT g, 1+(g%50), (ARRAY['华东','华北','华南','西南'])[1+(g%4)], 0, "
            "(ARRAY['paid','paid','paid','paid','paid','paid','paid','refunded','refunded','pending'])[1+(g%10)], "
            "DATE '2026-01-01' + to_days(CAST(g%90 AS INTEGER)) FROM (SELECT unnest(generate_series(1,600)) AS g)")
con.execute("INSERT INTO items SELECT 1+((g-1)%600), 1+((g*7)%30), 1+(g%4), round((random()*390+10)::numeric,2) FROM (SELECT unnest(generate_series(1,1200)) AS g)")
con.execute("UPDATE orders o SET amount = s.amt FROM (SELECT order_id, sum(qty*unit_price) amt FROM items GROUP BY 1) s WHERE o.order_id=s.order_id")

# (name, sql, truth, defect, declares_grain, metric_kind)
CASES = [
  # ---- 正确 ----
  ('c01','SELECT region, sum(amount) v FROM orders WHERE status=\'paid\' GROUP BY 1','ok',None,None,'simple'),
  ('c02','SELECT category, count(*) v FROM products GROUP BY 1','ok',None,None,'simple'),
  ('c03','SELECT strftime(created_at,\'%Y-%m\') m, sum(amount) v FROM orders WHERE status=\'paid\' GROUP BY 1 ORDER BY 1','ok',None,None,'simple'),
  ('c04','SELECT region, count(DISTINCT order_id) v FROM orders WHERE status=\'paid\' GROUP BY 1','ok',None,None,'simple'),
  ('c05','SELECT sum(qty) v FROM items','ok',None,None,'simple'),
  ('c06','SELECT min(amount) v, max(amount) v2 FROM orders','ok',None,None,'simple'),
  ('c07','SELECT region, sum(amount)/count(DISTINCT order_id) aov FROM orders WHERE status=\'paid\' GROUP BY 1','ok',None,None,'ratio'),
  ('c08','SELECT status, count(*) v FROM orders GROUP BY 1 ORDER BY 1','ok',None,None,'simple'),
  ('c09','SELECT o.order_id, sum(i.qty*i.unit_price) v FROM orders o JOIN items i USING(order_id) GROUP BY 1','ok','order_id','simple'),
  ('c10','SELECT user_id, count(*) v FROM orders GROUP BY 1','ok','user_id','simple'),
  ('c11','SELECT category, count(DISTINCT o.order_id) v FROM orders o JOIN items i USING(order_id) JOIN products p USING(product_id) WHERE o.status=\'paid\' GROUP BY 1','ok',None,'simple'),
  ('c12','SELECT avg(amount) v FROM orders WHERE status=\'paid\'','ok',None,None,'avg'),
  ('c13','SELECT region, sum(amount) v FROM orders WHERE status=\'paid\' AND created_at >= DATE \'2026-05-01\' GROUP BY 1','ok',None,None,'simple'),
  ('c14','SELECT count(*) v FROM orders WHERE status=\'paid\' AND region=\'华东\'','ok',None,None,'simple'),
  ('c15','SELECT product_id, sum(qty) v FROM items GROUP BY 1','ok','product_id','simple'),
  ('c16','SELECT region, avg(amount) v FROM orders WHERE status=\'paid\' GROUP BY 1','ok',None,None,'avg'),
  ('c17','SELECT count(DISTINCT user_id) v FROM orders','ok',None,None,'simple'),
  # 合法空集（A1 的天然误报源）
  ('c18','SELECT sum(amount) v FROM orders WHERE status=\'paid\' AND created_at >= DATE \'2027-01-01\'','ok-empty',None,None,'simple'),
  ('c19','SELECT region, sum(amount) v FROM orders WHERE region=\'西北\' GROUP BY 1','ok-empty',None,None,'simple'),
  ('c20','SELECT product_id, sum(qty) v FROM items WHERE qty > 1000 GROUP BY 1','ok-empty',None,None,'simple'),
  # ---- 缺陷 ----
  ('d01','SELECT region, sum(amount) v FROM orders GROUP BY 1','defect','silent_missing_filter',None,'simple'),
  ('d02','SELECT r.region, sum(o.amount) v FROM orders o JOIN (SELECT DISTINCT region_id, region FROM (SELECT 1 region_id, \'x\' region)) r ON o.user_id = r.region_id GROUP BY 1','defect','silent_wrong_join',None,'simple'),
  ('d03','SELECT avg(qty) v FROM items','defect','silent_wrong_grain',None,'avg'),
  ('d04','SELECT sum(amount) v FROM orders WHERE status=\'PAID\'','defect','empty_wrong_value',None,'simple'),
  ('d05','SELECT category, sum(amount) v FROM orders o JOIN products p USING(product_id) WHERE status=\'paid\' GROUP BY 1','defect','empty_binder_ok_but_no_rows',None,'simple'),
  ('d06','SELECT o.order_id, o.region FROM orders o JOIN items i USING(order_id)','defect','grain_duplicate','order_id','simple'),
  ('d07','SELECT user_id, o.region FROM orders o JOIN items i USING(order_id)','defect','grain_duplicate','user_id','simple'),
  ('d08','SELECT region, sum(amount)/count(DISTINCT order_id) x, sum(sum(amount)/count(DISTINCT order_id)) OVER () total FROM orders WHERE status=\'paid\' GROUP BY 1','defect','nonadditive_sum',None,'ratio'),
  ('d09','SELECT region, avg(amount) a, sum(avg(amount)) OVER () t FROM orders GROUP BY 1','defect','nonadditive_avg',None,'avg'),
  ('d10','SELECT region, sum(amount) v FROM orders WHERE status=\'paid\' GROUP BY 1 HAVING sum(amount) > 1e9','defect','empty_unreachable_having',None,'simple'),
]

def rows(sql):
    try:
        return con.execute(sql).fetchall()
    except Exception as e:
        return ('ERR', str(e))

def a1_empty(rs):
    return isinstance(rs, list) and len(rs) == 0

def a2_grain(sql, rs, grain):
    if not grain or not isinstance(rs, list) or not rs:
        return False
    idx = {'order_id': 0, 'user_id': 0, 'product_id': 0}.get(grain, 0)
    keys = [r[idx] for r in rs]
    return len(keys) != len(set(keys))

NONADD = {'ratio', 'avg'}

def a3_invariant(sql, kind):
    """检测对 non_additive 指标再做聚合（SUM/AVG 套在比率/均值外层）"""
    up = sql.upper()
    if kind in NONADD:
        if 'SUM(' in up and ('/COUNT' in up.replace(' ', '') or 'AVG(' in up):
            # 粗判：外层 SUM/AVG 包住了内层比率或均值
            if 'OVER ()' in up or 'SUM(AVG' in up or 'SUM(SUM(' in up:
                return True
    return False

report = []
for _c in CASES:
    _c = tuple(_c) + (None,) * (6 - len(_c))
    name, sql, truth, defect, grain, kind = _c
    rs = rows(sql)
    if isinstance(rs, tuple) and rs and rs[0] == 'ERR':
        report.append({'name': name, 'truth': truth, 'defect': defect, 'exec': 'ERR', 'a1': None, 'a2': None, 'a3': None})
        continue
    r = {'name': name, 'truth': truth, 'defect': defect, 'nrows': len(rs),
         'a1': a1_empty(rs), 'a2': a2_grain(sql, rs, grain), 'a3': a3_invariant(sql, kind)}
    r['any'] = r['a1'] or r['a2'] or r['a3']
    report.append(r)

def stats(pred_key):
    tp = sum(1 for x in report if x['truth'] == 'defect' and x.get(pred_key))
    fn = sum(1 for x in report if x['truth'] == 'defect' and not x.get(pred_key))
    fp = sum(1 for x in report if x['truth'].startswith('ok') and x.get(pred_key))
    tn = sum(1 for x in report if x['truth'].startswith('ok') and not x.get(pred_key))
    tpr = tp / (tp + fn) if tp + fn else 0
    fpr = fp / (fp + tn) if fp + tn else 0
    prec = tp / (tp + fp) if tp + fp else 0
    return {'tp': tp, 'fn': fn, 'fp': fp, 'tn': tn, 'TPR': round(tpr, 3), 'FPR': round(fpr, 3), 'precision': round(prec, 3)}

out = {'per_level': {k: stats(k) for k in ('a1', 'a2', 'a3', 'any')}, 'cases': report}
print(json.dumps(out['per_level'], ensure_ascii=False, indent=1))
print("\n明细：")
for x in report:
    flag = ''.join(k.upper() for k in ('a1','a2','a3') if x.get(k))
    print(f"  {x['name']} {x['truth']:<10} {str(x.get('defect') or ''):<32} rows={x.get('nrows')} fire={flag or '-'}")
json.dump(out, open('/tmp/poc29_results.json','w'), ensure_ascii=False, indent=1)

# 关键：A1 对"合法空集"的误报
legit_empty = [x for x in report if x['truth'] == 'ok-empty']
print(f"\n合法空集 {len(legit_empty)} 条中 A1 误报 {sum(1 for x in legit_empty if x['a1'])} 条")
