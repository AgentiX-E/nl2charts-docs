"""POC-7c：LLM 抽词 + 别名表定口径（三层分离）

上一版实验的错误：别名表里「销售额」只挂给 sales_amount，
于是系统"确定地"认为它不歧义 —— 而真实业务里「销售额」可能指
sales_amount / net_revenue / gross_revenue 三者之一。

正确做法：一个词挂多个指标，冲突本身就是歧义信号。
LLM 只负责「用户提到了哪些词」，不负责「这个词是哪个指标」。
"""
import json, os, urllib.request, time
from collections import defaultdict

KEY = os.environ['DEEPSEEK_KEY']
URL = 'https://api.deepseek.com/chat/completions'

# ===== 建模期：一个词可以挂多个指标（这才是真实业务） =====
METRIC_ALIASES = {
    "net_revenue":      ["净收入", "净销售额", "实收", "销售额", "收入", "营收"],
    "gross_revenue":    ["总收入", "含退款收入", "销售额", "收入"],
    "revenue":          ["收入", "营收", "营业收入", "营业额"],
    "sales_amount":     ["销售额", "销售金额", "下单金额", "流水", "成交额"],
    "gmv":              ["GMV", "成交额", "成交总额", "流水"],
    "order_count":      ["订单数", "订单量", "单量"],
    "paid_order_count": ["支付订单数", "成交单数"],
    "refund_amount":    ["退款额", "退款金额"],
    "aov":              ["客单价", "平均客单价", "人均消费"],
    "gross_profit":     ["毛利", "毛利额"],
    "gross_margin":     ["毛利率"],
}
# 「明确无歧义」的词：只挂一个指标
UNAMBIGUOUS = {"净收入": "net_revenue", "净销售额_hint": None}

alias2metrics = defaultdict(list)
for m, als in METRIC_ALIASES.items():
    for a in als:
        alias2metrics[a].append(m)

conflicts = {a: sorted(ms) for a, ms in alias2metrics.items() if len(ms) > 1}
print("=== 建模期冲突（别名表自检，应报警给人确认）===")
for a, ms in sorted(conflicts.items()):
    print(f"  '{a}' → {ms}")

SYSTEM = """你是术语抽取器。只输出用户问题里**出现过的业务术语原词**，不要映射到指标名，不要判断口径。

输出格式（严格）：
{"metric_terms":["<用户原话里的指标类词>"],"dimension_terms":["<维度类词>"],"time_terms":["<时间词>"]}

示例：
问题「上月各区域销售额」
输出 {"metric_terms":["销售额"],"dimension_terms":["区域"],"time_terms":["上月"]}

硬规则：
R1 只抽用户**原话里出现**的词，不要补全、不要同义改写、不要翻译
R2 抽不到就返回空数组
R3 不要输出解释
只输出 JSON。"""


def call(payload, timeout=90):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def resolve(terms):
    """确定性解析：一个词 → 多个指标 = 歧义"""
    out = {}
    for t in terms:
        t = t.strip()
        ms = sorted(set(alias2metrics.get(t, [])))
        if not ms:
            out[t] = {"status": "UNKNOWN", "candidates": []}
        elif len(ms) > 1:
            out[t] = {"status": "AMBIGUOUS", "candidates": ms}
        else:
            out[t] = {"status": "RESOLVED", "metric": ms[0]}
    return out


TESTS = [
    ("上月销售额",        "AMBIGUOUS"),
    ("各区域收入",        "AMBIGUOUS"),
    ("本月营业额",        "revenue"),
    ("各渠道营收",        "AMBIGUOUS"),
    ("上月流水",          "AMBIGUOUS"),
    ("各品类销售业绩",    "UNKNOWN"),
    ("本月毛利",          "gross_profit"),
    ("各区域客单价",      "aov"),
    ("上月成交额",        "AMBIGUOUS"),
    ("各渠道收入情况",    "AMBIGUOUS"),
    ("上月各区域净收入",  "net_revenue"),
    ("本季度支付订单数按渠道", "paid_order_count"),
    ("各品类退款额",      "refund_amount"),
    ("上周各渠道订单数",  "order_count"),
    ("各区域毛利率",      "gross_margin"),
]

rows = []
for q, expect in TESTS:
    body = call({"model": "deepseek-chat",
                 "messages": [{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": q}],
                 "temperature": 0, "max_tokens": 200,
                 "response_format": {"type": "json_object"}})
    content = body['choices'][0]['message']['content']
    try:
        obj = json.loads(content)
    except Exception:
        obj = {}
    terms = obj.get('metric_terms') or []
    res = resolve(terms)
    # 汇总判定
    statuses = {v['status'] for v in res.values()} or {'EMPTY'}
    if 'AMBIGUOUS' in statuses:
        verdict = 'AMBIGUOUS'
    elif statuses == {'RESOLVED'}:
        names = [v['metric'] for v in res.values()]
        verdict = names[0] if len(set(names)) == 1 else 'AMBIGUOUS'
    elif 'UNKNOWN' in statuses and 'RESOLVED' not in statuses:
        verdict = 'UNKNOWN'
    elif 'RESOLVED' in statuses and 'UNKNOWN' in statuses:
        verdict = next(v['metric'] for v in res.values() if v['status'] == 'RESOLVED')
    else:
        verdict = 'EMPTY'
    ok = verdict == expect
    rows.append({"q": q, "expect": expect, "terms": terms, "verdict": verdict, "ok": ok})
    mark = '✓' if ok else '✗'
    detail = "; ".join(f"{k}→{v['status'][:4]}" for k, v in res.items()) or "(空)"
    print(f"  {mark} {q[:14]:16s} terms={str(terms)[:26]:28s} → {verdict:16s} [{detail}]")

ok_n = sum(1 for r in rows if r['ok'])
print(f"\n三层方案（LLM 抽词 + 别名定口径）准确率: {ok_n}/{len(rows)} = {ok_n/len(rows)*100:.0f}%")

# 分项
amb = [r for r in rows if r['expect'] == 'AMBIGUOUS']
amb_ok = sum(1 for r in amb if r['ok'])
print(f"  真歧义 {amb_ok}/{len(amb)} = {amb_ok/len(amb)*100:.0f}%")
non = [r for r in rows if r['expect'] != 'AMBIGUOUS']
non_ok = sum(1 for r in non if r['ok'])
print(f"  应明确 {non_ok}/{len(non)} = {non_ok/len(non)*100:.0f}%")

json.dump(rows, open('/tmp/poc7/three_layer.json', 'w'), ensure_ascii=False, indent=1)
print("\n=== 三方对比（同一批真歧义题）===")
print("  A. 纯 LLM 判断歧义（40 指标 schema）:  2/8  = 25%")
print("  B. 单纯别名匹配（别名不冲突）:        会「确定地选错」，检测不到歧义")
print(f"  C. LLM 抽词 + 别名冲突检测:           {amb_ok}/{len(amb)} = {amb_ok/len(amb)*100:.0f}%")
