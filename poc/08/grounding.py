"""POC-8d：样例值在「生成阶段」（值接地）是否有独立价值？

检索阶段已证明样例值无边际贡献（+0.0pp）。但生成 SQL 时，
模型需要知道 status 的真实取值是 'completed' 还是 'COMPLETED'。
这是两个不同用途，必须分开测。

组 A：schema card 不含样例值
组 B：schema card 含样例值
判据：生成的 SQL 里，字符串字面量是否与真实取值精确一致（大小写敏感）
"""
import json, os, urllib.request, time, re

DS_KEY = os.environ['DEEPSEEK_KEY']
URL = 'https://api.deepseek.com/chat/completions'

TABLE = "dwd_order(order_id BIGINT, cust_id BIGINT, order_dt DATE, status VARCHAR, chan_id INT, total_amt DECIMAL, xse DECIMAL)"
SAMPLES = {
  "status": ["completed", "refunded", "pending", "cancelled"],
  "chan_id": ["1", "3", "7"],
}

QUESTIONS = [
 ("已完成订单的金额合计", "status = 'completed'"),
 ("哪些订单已退款", "status = 'refunded'"),
 ("待处理订单有多少", "status = 'pending'"),
 ("已取消的订单数", "status = 'cancelled'"),
 ("统计所有已完成和待处理订单", "status IN ('completed','pending')"),
 ("退款订单的总金额", "status = 'refunded'"),
 ("未完成的订单", "status != 'completed'"),
 ("按状态分组统计订单数", "GROUP BY status"),
 ("已完成的订单按渠道汇总", "status = 'completed'"),
 ("排除已取消订单", "status != 'cancelled'"),
]

SYS_BASE = f"""你是 SQL 生成器。只输出一条 DuckDB SELECT 语句，不要解释。

表结构：
  {TABLE}
"""

SYS_SAMPLES = SYS_BASE + f"""
字段取值样例：
  status: {', '.join(SAMPLES['status'])}
  chan_id: {', '.join(SAMPLES['chan_id'])}
"""


def call(sysmsg, q):
    payload = {"model": "deepseek-chat",
               "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": q}],
               "temperature": 0, "max_tokens": 300}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {DS_KEY}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    return d['choices'][0]['message']['content']


def extract_literals(sql):
    """提取 SQL 里的所有单引号字面量"""
    return re.findall(r"'([^']*)'", sql)


def judge(sql, expect_vals):
    """判据：期望的取值字面量全部出现在 SQL 里，且没有大小写变体"""
    lits = extract_literals(sql)
    lowered = {l.lower() for l in lits}
    ok = True
    detail = []
    for v in expect_vals:
        if v.lower() not in lowered:
            ok = False; detail.append(f"missing:{v}")
        elif v not in lits:
            ok = False; detail.append(f"case:{[l for l in lits if l.lower()==v.lower()]}")
    return ok, detail, lits


def run(label, sysmsg):
    rows = []
    for q, expect in QUESTIONS:
        try:
            sql = call(sysmsg, q).strip()
        except Exception as e:
            rows.append({"q": q, "err": str(e)[:80]}); continue
        # 从期望表达式里抽出字面量
        exp_vals = re.findall(r"'([^']*)'", expect)
        if not exp_vals:
            ok, detail, lits = True, [], extract_literals(sql)   # 无字面量要求
            ok = 'status' in sql.lower()
        else:
            ok, detail, lits = judge(sql, exp_vals)
        rows.append({"q": q, "sql": sql[:160], "ok": ok, "detail": detail, "lits": lits})
    passed = sum(1 for r in rows if r.get('ok'))
    print(f"\n### {label}  通过 {passed}/{len(rows)}")
    for r in rows:
        if not r.get('ok'):
            print(f"  ✗ {r['q'][:18]:20s} {r.get('detail') or r.get('err','')}  |  {r.get('sql','')[:90]}")
    return {"label": label, "passed": passed, "n": len(rows), "rows": rows}


if __name__ == '__main__':
    print("对比：schema card 带/不带样例值，对「值接地」的影响")
    a = run("A 无样例值", SYS_BASE)
    time.sleep(1)
    b = run("B 带样例值", SYS_SAMPLES)
    print(f"\n=== 结论 ===")
    print(f"  A 无样例值: {a['passed']}/{a['n']}")
    print(f"  B 带样例值: {b['passed']}/{b['n']}")
    print(f"  差值: {(b['passed']-a['passed'])/a['n']*100:+.0f}pp")
    json.dump({"A": a, "B": b}, open('/tmp/poc8/grounding.json','w'), ensure_ascii=False, indent=1)
