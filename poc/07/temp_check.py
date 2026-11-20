import json, os, urllib.request, time

KEY=os.environ['DEEPSEEK_KEY']; URL='https://api.deepseek.com/chat/completions'
def call(p):
    req=urllib.request.Request(URL,data=json.dumps(p).encode(),
        headers={'Authorization':f'Bearer {KEY}','Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=90) as r: return json.loads(r.read())

sysmsg = "只输出 JSON，不要解释。问题：上月各区域净收入，可用指标 net_revenue/order_count，可用维度 region/order_month。"

print("=== temperature 是否生效（同一 prompt 各跑 5 次）===")
for t in (0.0, 1.0):
    outs, toks = [], []
    for i in range(5):
        b = call({"model":"deepseek-chat","messages":[{"role":"system","content":sysmsg}],
                  "temperature":t,"max_tokens":120,"response_format":{"type":"json_object"}})
        c = b['choices'][0]['message']['content']
        outs.append(c)
        toks.append((b['usage']['prompt_tokens'], b['usage']['completion_tokens']))
    uniq = len(set(outs))
    print(f"  temp={t}: 5 次中 {uniq} 种不同输出 | tokens={toks[0]} | 示例={outs[0][:70]!r}")
