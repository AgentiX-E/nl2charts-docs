import json, os, urllib.request, time

KEY = os.environ['DEEPSEEK_KEY']
URL = 'https://api.deepseek.com/chat/completions'

def call(payload, timeout=90):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), time.time()-t0, None
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:400]
        return None, time.time()-t0, f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, time.time()-t0, str(e)[:200]

SCHEMA = {
  "type": "object",
  "properties": {
    "metrics": {"type": "array", "items": {"type": "string", "enum": ["net_revenue","order_count","aov","refund_amount"]}},
    "dimensions": {"type": "array", "items": {"type": "string", "enum": ["region","order_month","channel","category"]}},
    "filters": {"type": "array", "items": {"type": "object","properties": {"field":{"type":"string"},"op":{"type":"string","enum":["=",">","<",">=","<=","in"]},"value":{}},"required":["field","op","value"],"additionalProperties": False}}
  },
  "required": ["metrics","dimensions","filters"],
  "additionalProperties": False
}

PROMPT = """你是分析查询解析器。只输出 MetricQuery JSON，不输出 SQL，不解释。

可用指标：net_revenue(净收入), order_count(订单数), aov(客单价), refund_amount(退款额)
可用维度：region(区域), order_month(月), channel(渠道), category(品类)

问题：上月各区域净收入"""

print("=== A. response_format 能力探测 ===")
for name, rf in [
    ("json_object", {"type": "json_object"}),
    ("json_schema(strict)", {"type": "json_schema", "json_schema": {"name": "mq", "strict": True, "schema": SCHEMA}}),
    ("json_schema(no strict)", {"type": "json_schema", "json_schema": {"name": "mq", "schema": SCHEMA}}),
]:
    body, dt, err = call({"model": "deepseek-chat", "messages":[{"role":"user","content":PROMPT}],
                          "response_format": rf, "max_tokens": 400, "temperature": 0})
    if err:
        print(f"  {name:24s} ✗ {err[:150]}")
    else:
        c = body['choices'][0]['message']['content']
        print(f"  {name:24s} ✓ {dt:.1f}s  finish={body['choices'][0].get('finish_reason')}  head={c[:60]!r}")
