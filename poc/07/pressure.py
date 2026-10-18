import json, os, urllib.request, time, re, statistics
from collections import Counter

KEY = os.environ['DEEPSEEK_KEY']
URL = 'https://api.deepseek.com/chat/completions'

# 真实规模：40 指标（含 8 组近义）+ 20 维度
METRICS = {
  "net_revenue": "净收入（剔除退款与测试单）",
  "gross_revenue": "总收入（未扣退款）",
  "revenue": "收入（口径待定，历史遗留）",
  "net_sales": "净销售额（除税）",
  "sales_amount": "销售金额（下单口径）",
  "order_count": "订单数",
  "paid_order_count": "支付订单数",
  "refund_amount": "退款额",
  "refund_count": "退款单数",
  "aov": "客单价",
  "gmv": "GMV",
  "units_sold": "销售件数",
  "customer_count": "下单客户数",
  "new_customer_count": "新客数",
  "returning_customer_count": "复购客户数",
  "discount_amount": "优惠金额",
  "shipping_fee": "运费",
  "tax_amount": "税额",
  "cost_of_goods": "商品成本",
  "gross_profit": "毛利额",
  "gross_margin": "毛利率",
  "avg_order_items": "平均每单件数",
  "avg_discount_rate": "平均折扣率",
  "conversion_rate": "转化率",
  "cart_abandon_rate": "购物车放弃率",
  "stock_qty": "库存数量",
  "stock_turnover": "库存周转率",
  "inventory_days": "库存天数",
  "click_count": "点击数",
  "pv": "页面浏览量",
  "uv": "独立访客数",
  "ctr": "点击率",
  "cpc": "单次点击成本",
  "roi": "投产比",
  "ad_spend": "广告花费",
  "signup_count": "注册数",
  "unsubscribe_count": "退订数",
  "session_count": "会话数",
  "avg_session_duration": "平均会话时长",
  "bounce_rate": "跳出率",
}
DIMS = {
  "region": "大区（华东/华南/华北/西南/东北）",
  "province": "省份",
  "city": "城市",
  "order_month": "订单月",
  "order_date": "订单日",
  "order_week": "订单周",
  "channel": "渠道（自营/天猫/京东/抖音/线下）",
  "category": "品类",
  "subcategory": "子品类",
  "brand": "品牌",
  "sku": "SKU",
  "product": "商品",
  "customer_segment": "客户分层",
  "member_level": "会员等级",
  "payment_method": "支付方式",
  "campaign": "营销活动",
  "device": "设备类型",
  "warehouse": "仓库",
  "store": "门店",
  "supplier": "供应商",
}

SYSTEM = f"""你是分析查询解析器。只输出 MetricQuery JSON，不输出 SQL，不解释。

可用指标（{len(METRICS)} 个）：
{chr(10).join(f'  {k}({v})' for k, v in METRICS.items())}

可用维度（{len(DIMS)} 个）：
{chr(10).join(f'  {k}({v})' for k, v in DIMS.items())}

输出格式（严格，只能有这三个键）：
{{"metrics":["<指标名>"],"dimensions":["<维度名>"],"filters":[{{"field":"<字段>","op":"=","value":"<值>"}}]}}

硬规则：
R1 指标不存在 → {{"error":"METRIC_NOT_FOUND","candidates":["<最多3个最接近的指标名>"]}}
R2 存在多种口径（同义词/口径未定）→ {{"error":"AMBIGUOUS","candidates":["<2-3个真正有区分度的候选>"]}}
R3 时间不明确 → 不猜，dimensions 里不放时间维度

严格禁止：写 SQL、编造指标名、输出任何解释文字、输出额外键。"""

# 30 题：A 明确 8 / B 多指标 6 / C 不存在 6 / E 同义歧义 10
QUESTIONS = [
    ("A", "上月各区域净收入"),
    ("A", "本季度支付订单数按渠道"),
    ("A", "各品类退款额"),
    ("A", "上月客单价按区域"),
    ("A", "今年各月净收入"),
    ("A", "上周各渠道订单数"),
    ("A", "各区域毛利额"),
    ("A", "本月各品类购物车放弃率"),
    ("B", "上月各区域净收入、订单数和客单价"),
    ("B", "按渠道和品类看退款额与订单数"),
    ("B", "今年每个月各区域的净收入和客单价"),
    ("B", "各品类订单数、退款额，按渠道拆分"),
    ("B", "上月各渠道的客单价和订单数对比"),
    ("B", "近三个月各区域净收入"),
    ("C", "上月客户满意度"),
    ("C", "各区域员工人数"),
    ("C", "本月服务器响应时间"),
    ("C", "各渠道合同违约率"),
    ("C", "上月碳排放量"),
    ("C", "各品类专利数量"),
    ("E", "上月销售额"),
    ("E", "各区域收入"),
    ("E", "本月营业额"),
    ("E", "各渠道营收"),
    ("E", "上月流水"),
    ("E", "各品类销售业绩"),
    ("E", "本月毛利"),
    ("E", "各区域客单价"),
    ("E", "上月成交额"),
    ("E", "各渠道收入情况"),
]


def call(payload, timeout=120):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = json.loads(r.read())
            return b, time.time() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.time() - t0, f"HTTP {e.code}: {e.read().decode()[:160]}"
    except Exception as e:
        return None, time.time() - t0, str(e)[:120]


def extract_json(text):
    try:
        return json.loads(text), 'direct'
    except Exception:
        pass
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            return json.loads(m.group(0)), 'extracted'
        except Exception:
            return None, 'extract_failed'
    return None, 'no_json'


ALLOWED_TOP = {'metrics', 'dimensions', 'filters', 'error', 'candidates'}

def validate(obj, cls):
    """严格校验；对 E 类额外要求'必须触发 AMBIGUOUS 且候选取自近义组'"""
    issues = []
    if not isinstance(obj, dict):
        return ['not_object']
    extra = set(obj) - ALLOWED_TOP
    if extra:
        issues.append('extra_keys:' + ','.join(sorted(extra)))
    if 'error' in obj:
        if obj['error'] not in ('METRIC_NOT_FOUND', 'AMBIGUOUS'):
            issues.append('bad_error_code')
        cands = obj.get('candidates')
        if not isinstance(cands, list) or not cands:
            issues.append('bad_candidates')
        else:
            bad = [c for c in cands if c not in METRICS and c not in DIMS]
            if bad:
                issues.append('hallucinated_candidate:' + ','.join(map(str, bad)))
        # E 类应触发 AMBIGUOUS
        if cls == 'E' and obj['error'] != 'AMBIGUOUS':
            issues.append('should_be_ambiguous')
        # C 类不应给 metrics
        return issues

    for k in ('metrics', 'dimensions', 'filters'):
        if k not in obj:
            issues.append(f'missing_{k}')
    ms = obj.get('metrics') or []
    ds = obj.get('dimensions') or []
    if not isinstance(ms, list) or not isinstance(ds, list):
        return issues + ['wrong_type']
    bad_m = [m for m in ms if m not in METRICS]
    bad_d = [d for d in ds if d not in DIMS]
    if bad_m:
        issues.append('hallucinated_metric:' + ','.join(map(str, bad_m)))
    if bad_d:
        issues.append('hallucinated_dimension:' + ','.join(map(str, bad_d)))
    if not ms:
        issues.append('empty_metrics')
    # E 类若给了 metrics 而非 AMBIGUOUS，视为"静默选一个口径"
    if cls == 'E' and not issues:
        issues.append('silent_disambiguation:' + ','.join(map(str, ms)))
    # C 类若给了 metrics，视为幻觉
    if cls == 'C' and ms:
        issues.append('hallucinated_for_nonexistent')
    return issues


def run(mode):
    rows = []
    for cls, q in QUESTIONS:
        p = {"model": "deepseek-chat",
             "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}],
             "temperature": 0, "max_tokens": 600}
        if mode == 'json_object':
            p["response_format"] = {"type": "json_object"}
        body, dt, err = call(p)
        if err:
            rows.append({"cls": cls, "q": q, "err": err, "ms": dt*1000, "issues": ["request_error"]})
            continue
        c = body['choices'][0]['message']['content']
        obj, how = extract_json(c)
        issues = validate(obj, cls) if obj is not None else ['parse_failed']
        rows.append({"cls": cls, "q": q, "ms": dt*1000, "how": how,
                     "issues": issues, "ok": not issues,
                     "usage": body.get('usage', {}), "head": c[:110]})
    return rows


def report(label, rows):
    n = len(rows)
    def cnt(pred): return sum(1 for r in rows if pred(r))
    parse_fail = cnt(lambda r: 'parse_failed' in r['issues'] or 'request_error' in r['issues'])
    extra = cnt(lambda r: any(i.startswith('extra_keys') for i in r['issues']))
    halluc = cnt(lambda r: any(i.startswith('hallucinated') for i in r['issues']))
    silent = cnt(lambda r: any(i.startswith('silent_disambiguation') for i in r['issues']))
    ok = cnt(lambda r: r.get('ok'))
    ms = sorted(r['ms'] for r in rows if 'ms' in r)
    tin = sum((r.get('usage') or {}).get('prompt_tokens', 0) for r in rows)
    print(f"\n### {label}  n={n}")
    print(f"  解析/请求失败   {parse_fail:3d} ({parse_fail/n*100:4.0f}%)")
    print(f"  额外字段污染     {extra:3d} ({extra/n*100:4.0f}%)")
    print(f"  编造名称         {halluc:3d} ({halluc/n*100:4.0f}%)")
    print(f"  **静默选口径**   {silent:3d} ({silent/n*100:4.0f}%)   ← E 类未触发 AMBIGUOUS")
    print(f"  **完全通过**     {ok:3d} ({ok/n*100:4.0f}%)")
    if ms:
        print(f"  延迟 p50={statistics.median(ms):.0f}ms p95={ms[int(len(ms)*.95)-1]:.0f}ms")
    print(f"  token in/out = {tin}/{sum((r.get('usage') or {}).get('completion_tokens',0) for r in rows)}")
    print(f"  平均 in/题 = {tin//n}")

    print(f"  逐类:", end=' ')
    for c in 'ABCE':
        sub = [r for r in rows if r['cls'] == c]
        if sub:
            print(f"{c}={sum(1 for r in sub if r.get('ok'))}/{len(sub)}", end='  ')
    print()
    return {"n": n, "ok": ok, "parse_fail": parse_fail, "extra": extra,
            "halluc": halluc, "silent": silent, "p50": statistics.median(ms) if ms else 0,
            "tok_in": tin}


if __name__ == '__main__':
    res = {}
    for mode in ('plain', 'json_object'):
        rows = run(mode)
        res[mode] = {"summary": report(mode, rows), "rows": rows}
    json.dump(res, open('/tmp/poc7/pressure.json', 'w'), ensure_ascii=False, indent=1)
    print("\n保存 /tmp/poc7/pressure.json")
    print("\n=== E 类（同义歧义）明细 ===")
    for mode in res:
        print(f"\n[{mode}]")
        for r in res[mode]['rows']:
            if r['cls'] == 'E':
                mark = '✓' if r.get('ok') else '✗'
                print(f"  {mark} {r['q'][:14]:16s} {r['head'][:88]}")
