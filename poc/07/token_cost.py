import json, os, urllib.request, statistics
KEY=os.environ['DEEPSEEK_KEY']; URL='https://api.deepseek.com/chat/completions'
def call(p):
    req=urllib.request.Request(URL,data=json.dumps(p).encode(),
        headers={'Authorization':f'Bearer {KEY}','Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=90) as r: return json.loads(r.read())

SCHEMA_TXT = "\n".join(f"  m{i}=指标{i}（说明{i}）" for i in range(40)) + "\n" + \
             "\n".join(f"  d{i}=维度{i}" for i in range(20))

QS = ["上月各区域净收入","本季度订单数按渠道","各品类退款额","上月客单价按区域",
      "今年各月净收入","上周各渠道订单数","各区域毛利额","本月各品类购物车放弃率"]

CONFIGS = {
 "A 直出 MetricQuery": ("你是解析器。可用指标：\n"+SCHEMA_TXT+"\n只输出 JSON：{\"metrics\":[],\"dimensions\":[],\"filters\":[]}"),
 "B 只抽词": ("你是术语抽取器。只输出 JSON：{\"metric_terms\":[],\"dimension_terms\":[],\"time_terms\":[]}\n只抽用户原话里的词。"),
}

res={}
for name,(sysmsg) in CONFIGS.items():
    tok_in=[]; tok_out=[]; lat=[]
    for q in QS:
        b=call({"model":"deepseek-chat","messages":[{"role":"system","content":sysmsg},{"role":"user","content":q}],
                "temperature":0,"max_tokens":400,"response_format":{"type":"json_object"}})
        u=b['usage']; tok_in.append(u['prompt_tokens']); tok_out.append(u['completion_tokens'])
    res[name]=(statistics.mean(tok_in), statistics.mean(tok_out))
    print(f"  {name:22s} in={statistics.mean(tok_in):6.0f}  out={statistics.mean(tok_out):5.1f}")

print()
for k,(i,o) in res.items():
    print(f"  {k}: 单题 {i+o:.0f} tokens")
