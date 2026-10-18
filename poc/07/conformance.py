import json, os, urllib.request, time, re, statistics

KEY = os.environ['DEEPSEEK_KEY']
URL = 'https://api.deepseek.com/chat/completions'

METRICS = ["net_revenue", "order_count", "aov", "refund_amount"]
DIMS = ["region", "order_month", "channel", "category"]
OPS = ["=", ">", "<", ">=", "<=", "in"]

SYSTEM = """你是分析查询解析器。只输出 MetricQuery JSON，不输出 SQL，不解释。

可用指标：net_revenue(净收入), order_count(订单数), aov(客单价), refund_amount(退款额)
可用维度：region(区域), order_month(月), channel(渠道), category(品类)

输出格式（严格）：
{"metrics":["<指标名>"],"dimensions":["<维度名>"],"filters":[{"field":"<字段>","op":"<运算符>","value":<值>}]}

硬规则：
R1 指标不存在 → 输出 {"error":"METRIC_NOT_FOUND","candidates":["<最接近的指标名>"]}
R2 存在多种口径 → 输出 {"error":"AMBIGUOUS","candidates":["<可能的口径>"]}
R3 时间不明确 → 不猜

反例：✗ 写 SQL ✗ 编造指标名 ✗ 输出解释文字"""

# 40 题，四类各 10：明确 / 多指标多维度 / 不存在指标 / 歧义或模糊
QUESTIONS = [
    # A 明确（10）
    ("A", "上月各区域净收入"),
    ("A", "本季度订单数按渠道"),
    ("A", "各品类退款额"),
    ("A", "上月客单价按区域"),
    ("A", "今年各月净收入"),
    ("A", "上周各渠道订单数"),
    ("A", "各区域退款额占比"),
    ("A", "本月各品类客单价"),
    ("A", "最近30天净收入按渠道"),
    ("A", "各区域订单数"),
    # B 多指标 / 多维度（10）
    ("B", "上月各区域净收入、订单数和客单价"),
    ("B", "按渠道和品类看退款额与订单数"),
    ("B", "今年每个月各区域的净收入和客单价"),
    ("B", "各品类订单数、退款额，按渠道拆分"),
    ("B", "上月各渠道的客单价和订单数对比"),
    ("B", "近三个月各区域净收入趋势"),
    ("B", "各品类净收入和退款额"),
    ("B", "按区域、渠道统计订单数和客单价"),
    ("B", "本月各品类退款额与净收入"),
    ("B", "各区域每月订单数"),
    # C 不存在指标（10）
    ("C", "上月毛利率"),
    ("C", "各区域库存周转率"),
    ("C", "本月新增用户数"),
    ("C", "各渠道转化率"),
    ("C", "上月客户满意度"),
    ("C", "各品类复购率"),
    ("C", "本季度人均消费"),
    ("C", "各区域退货率"),
    ("C", "上月广告ROI"),
    ("C", "各渠道获客成本"),
    # D 歧义 / 模糊（10）
    ("D", "最近表现怎么样"),
    ("D", "这个月比上个月好还是差"),
    ("D", "看看销售情况"),
    ("D", "帮我分析一下数据"),
    ("D", "哪个渠道最好"),
    ("D", "这几天怎么样"),
    ("D", "对比一下"),
    ("D", "趋势如何"),
    ("D", "哪个区域表现最差"),
    ("D", "有没有异常"),
]


def call(payload, timeout=120):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), time.time() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.time() - t0, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return None, time.time() - t0, str(e)[:160]


def extract_json(text):
    """模拟 P1 层：先直接 parse，失败则提取首个 {...}"""
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


def validate(obj):
    """模拟 P2/P3 层：结构 + 语义"""
    issues = []
    if not isinstance(obj, dict):
        return ['not_object']
    extra = set(obj) - {'metrics', 'dimensions', 'filters', 'error', 'candidates'}
    if extra:
        issues.append('extra_keys:' + ','.join(sorted(extra)))
    if 'error' in obj:
        if obj['error'] not in ('METRIC_NOT_FOUND', 'AMBIGUOUS'):
            issues.append('bad_error_code')
        if not isinstance(obj.get('candidates'), list):
            issues.append('missing_candidates')
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
    for f in (obj.get('filters') or []):
        if not isinstance(f, dict) or set(f) - {'field', 'op', 'value'}:
            issues.append('bad_filter_shape')
            break
        if f.get('op') not in OPS:
            issues.append('bad_op')
            break
    return issues


def run(mode, temp, limit=None):
    qs = QUESTIONS[:limit] if limit else QUESTIONS
    rows = []
    for i, (cls, q) in enumerate(qs):
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": q}],
            "temperature": temp,
            "max_tokens": 500,
        }
        if mode == 'json_object':
            payload["response_format"] = {"type": "json_object"}
        body, dt, err = call(payload)
        if err:
            rows.append({"cls": cls, "q": q, "err": err, "ms": dt * 1000})
            continue
        content = body['choices'][0]['message']['content']
        obj, how = extract_json(content)
        issues = validate(obj) if obj is not None else ['parse_failed']
        rows.append({
            "cls": cls, "q": q, "ms": dt * 1000, "how": how,
            "ok": not issues, "issues": issues,
            "usage": body.get('usage', {}),
            "head": content[:80],
        })
    return rows


def summarize(label, rows):
    n = len(rows)
    errs = [r for r in rows if 'err' in r]
    ok = [r for r in rows if r.get('ok')]
    parse_fail = [r for r in rows if 'parse_failed' in (r.get('issues') or [])]
    extra = [r for r in rows if any(i.startswith('extra_keys') for i in (r.get('issues') or []))]
    halluc = [r for r in rows if any(i.startswith('hallucinated') for i in (r.get('issues') or []))]
    empty = [r for r in rows if 'empty_metrics' in (r.get('issues') or [])]
    ms = [r['ms'] for r in rows if 'ms' in r]
    tin = sum((r.get('usage') or {}).get('prompt_tokens', 0) for r in rows)
    tout = sum((r.get('usage') or {}).get('completion_tokens', 0) for r in rows)

    print(f"\n### {label}  n={n}")
    print(f"  请求失败      {len(errs):3d}  ({len(errs)/n*100:.0f}%)")
    print(f"  JSON 解析失败  {len(parse_fail):3d}  ({len(parse_fail)/n*100:.0f}%)")
    print(f"  额外字段污染   {len(extra):3d}  ({len(extra)/n*100:.0f}%)")
    print(f"  编造指标/维度  {len(halluc):3d}  ({len(halluc)/n*100:.0f}%)")
    print(f"  空 metrics    {len(empty):3d}")
    print(f"  **完全通过**   {len(ok):3d}  ({len(ok)/n*100:.0f}%)")
    if ms:
        ms.sort()
        print(f"  延迟 p50={statistics.median(ms):.0f}ms p95={ms[int(len(ms)*0.95)-1]:.0f}ms")
    print(f"  tokens in/out = {tin}/{tout}")
    return {"n": n, "ok": len(ok), "parse_fail": len(parse_fail),
            "extra": len(extra), "halluc": len(halluc), "errors": len(errs)}


if __name__ == '__main__':
    import sys
    results = {}
    for mode, temp in [("plain", 0.0), ("json_object", 0.0), ("json_object", 0.3)]:
        label = f"mode={mode} temp={temp}"
        rows = run(mode, temp)
        results[label] = {"summary": summarize(label, rows), "rows": rows}
        time.sleep(1)

    print("\n\n=== 逐类通过率 ===")
    print(f"{'配置':28s} {'A明确':>7s} {'B多指标':>8s} {'C不存在':>8s} {'D歧义':>7s}")
    for label, d in results.items():
        by = {}
        for r in d['rows']:
            by.setdefault(r['cls'], [0, 0])
            by[r['cls']][1] += 1
            if r.get('ok'):
                by[r['cls']][0] += 1
        cells = []
        for c in "ABCD":
            a, b = by.get(c, [0, 1])
            cells.append(f"{a}/{b}")
        print(f"{label:28s} {cells[0]:>7s} {cells[1]:>8s} {cells[2]:>8s} {cells[3]:>7s}")

    json.dump({k: v for k, v in results.items()}, open('/tmp/poc7/result.json', 'w'),
              ensure_ascii=False, indent=1)
    print("\n保存到 /tmp/poc7/result.json")
