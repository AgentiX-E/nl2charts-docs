"""POC-8b：列名完全不透明时，样例值还有价值吗？

v1 的缺陷：列名本身语义透明（total_amt / region_name），问题里含关键词，
embedding 只靠列名就能命中 → 三组无差异，测不出样例值的边际贡献。

v2 修正：
  - 全部用企业遗留系统的真实命名（f1/f2/attr_01/xse/djzt/v3…）
  - 问题用纯业务语言，绝不含列代号
  - 金标列 = 回答问题必需的那一列
  - 组别：A 仅代号 / B +中文注释 / C +注释+3 样例值
"""
import json, os, urllib.request, time, statistics, math, random

KEY = os.environ['ZHIPU_KEY']
URL = 'https://open.bigmodel.cn/api/paas/v4/embeddings'
MODEL = 'embedding-3'

# (table, col, type, comment, samples)
OPAQUE = [
 ("dwd_order","f1","BIGINT","订单唯一编号",["90000123","90000124"]),
 ("dwd_order","f2","BIGINT","下单客户编号",["C10023","C10088"]),
 ("dwd_order","f3","DATE","订单创建日期",["2026-09-15","2026-10-01"]),
 ("dwd_order","f4","DECIMAL","订单应付总额（含税，未扣退款）",["1288.00","356.50"]),
 ("dwd_order","f5","VARCHAR","订单当前处理状态",["completed","refunded","pending","cancelled"]),
 ("dwd_order","f6","INT","订单来源渠道编号",["1","3","7"]),
 ("dwd_order","attr_01","VARCHAR","订单来源终端类型",["app","miniapp","web","offline"]),
 ("dwd_order","xse","DECIMAL","销售额（内部口径）",["1288.00"]),
 ("dwd_order","djzt","VARCHAR","单据状态（旧系统枚举）",["1","2","9"]),
 ("dwd_cust","v1","BIGINT","客户编号",["C10023"]),
 ("dwd_cust","v2","VARCHAR","客户真实姓名",["张伟","李娜"]),
 ("dwd_cust","v3","DATE","客户首次注册日期",["2025-03-11"]),
 ("dwd_cust","v4","VARCHAR","客户价值分层等级",["diamond","gold","silver","normal"]),
 ("dwd_cust","hylx","VARCHAR","会员类型",["A","B","C"]),
 ("dwd_cust","v5","INT","客户归属大区编号",["3","5"]),
 ("dwd_prod","p1","BIGINT","商品唯一编号",["SKU9901"]),
 ("dwd_prod","p2","VARCHAR","商品展示名称",["无线耳机 Pro"]),
 ("dwd_prod","p3","DECIMAL","商品对外标价",["299.00"]),
 ("dwd_prod","p4","DECIMAL","商品采购成本价",["120.00"]),
 ("dwd_prod","cpdj","INT","产品等级（1 最高）",["1","2","3"]),
 ("dwd_prod","tstp","VARCHAR","商品上架标记",["Y","N"]),
 ("dwd_refund","r1","BIGINT","退款单编号",["77001"]),
 ("dwd_refund","r2","BIGINT","退款关联的订单编号",["90000123"]),
 ("dwd_refund","r3","DECIMAL","本次退款金额",["128.00"]),
 ("dwd_refund","r4","DATE","退款发生日期",["2026-09-20"]),
 ("dwd_refund","r5","VARCHAR","退款原因分类",["quality","wrong_item","no_reason","late"]),
 ("dwd_refund","tkly","VARCHAR","退款发起来源",["APP","CS","SYS"]),
 ("dwd_ship","s1","BIGINT","发货单编号",["66001"]),
 ("dwd_ship","s2","BIGINT","发货关联订单编号",["90000123"]),
 ("dwd_ship","s3","DATE","包裹发出日期",["2026-09-16"]),
 ("dwd_ship","s4","VARCHAR","承运物流商编码",["SF","JD","YTO","ZTO"]),
 ("dwd_ship","s5","DATE","包裹签收日期",["2026-09-18"]),
 ("dwd_ship","fhzt","VARCHAR","发货流转状态",["WAIT","SENT","DONE"]),
 ("dwd_inv","i1","BIGINT","库存记录商品编号",["SKU9901"]),
 ("dwd_inv","i2","INT","库存所在仓库编号",["2"]),
 ("dwd_inv","i3","INT","当前可用库存件数",["0","35","1200"]),
 ("dwd_inv","i4","DATE","库存统计快照日期",["2026-10-01"]),
 ("dwd_inv","aqkc","INT","安全库存阈值",["50"]),
]

# 问题 → 金标列（用业务语言，不含任何代号）
QUESTIONS = [
 ("上月销售额是多少", ["dwd_order.xse"]),
 ("订单应付总额合计", ["dwd_order.f4"]),
 ("哪些订单已经完成", ["dwd_order.f5"]),
 ("订单是从哪个终端下的", ["dwd_order.attr_01"]),
 ("旧系统里的单据状态怎么对应", ["dwd_order.djzt"]),
 ("客户姓名列表", ["dwd_cust.v2"]),
 ("客户是什么时候注册的", ["dwd_cust.v3"]),
 ("客户价值分层有哪些", ["dwd_cust.v4"]),
 ("会员类型分布", ["dwd_cust.hylx"]),
 ("商品的标价和成本分别是多少", ["dwd_prod.p3","dwd_prod.p4"]),
 ("产品等级怎么划分", ["dwd_prod.cpdj"]),
 ("商品是否已上架", ["dwd_prod.tstp"]),
 ("退款的原因有哪些", ["dwd_refund.r5"]),
 ("退款是从哪个入口发起的", ["dwd_refund.tkly"]),
 ("退款金额合计", ["dwd_refund.r3"]),
 ("用的是哪家快递", ["dwd_ship.s4"]),
 ("发货之后几天签收", ["dwd_ship.s3","dwd_ship.s5"]),
 ("当前的发货状态", ["dwd_ship.fhzt"]),
 ("哪些商品库存不足安全线", ["dwd_inv.i3","dwd_inv.aqkc"]),
 ("仓库里有几件货", ["dwd_inv.i3"]),
]


def embed(texts, batch=32, retries=3):
    out = []
    for i in range(0, len(texts), batch):
        chunk = texts[i:i+batch]
        for attempt in range(retries):
            try:
                req = urllib.request.Request(URL,
                    data=json.dumps({"model": MODEL, "input": chunk}).encode(),
                    headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=120) as r:
                    d = json.loads(r.read())
                out.extend([x['embedding'] for x in d['data']])
                break
            except Exception:
                if attempt == retries - 1: raise
                time.sleep(2 ** attempt)
    return out


def cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(x*x for x in b))
    return dot / (na * nb + 1e-9)


def index_text(t, c, ty, cmt, samples, level):
    if level == 'A':
        return f"{t}.{c}"
    if level == 'B':
        return f"{t}.{c}: {cmt}"
    return f"{t}.{c}: {cmt}; 常见取值 {', '.join(samples)}"


def run(level):
    texts = [index_text(*row, level) for row in OPAQUE]
    keys = [f"{r[0]}.{r[1]}" for r in OPAQUE]
    vecs = embed(texts)
    qvecs = embed([q for q, _ in QUESTIONS])

    per_q, hits5, hits10 = [], 0, 0
    for qi, (q, gold) in enumerate(QUESTIONS):
        scored = sorted(((cosine(qvecs[qi], v), k) for v, k in zip(vecs, keys)), reverse=True)
        top10 = [k for _, k in scored[:10]]
        r5 = len(set(gold) & set(top10[:5])) / len(gold)
        r10 = len(set(gold) & set(top10)) / len(gold)
        hits5 += (r5 == 1.0); hits10 += (r10 == 1.0)
        per_q.append({"q": q, "gold": gold, "rank": [top10.index(g)+1 if g in top10 else None for g in gold],
                      "r5": r5, "r10": r10, "top1": top10[0]})
    return {"level": level, "hits5": hits5, "hits10": hits10,
            "avg5": statistics.mean(p['r5'] for p in per_q),
            "avg10": statistics.mean(p['r10'] for p in per_q), "per_q": per_q}


if __name__ == '__main__':
    print(f"不透明 schema: {len(OPAQUE)} 列 / {len(QUESTIONS)} 题 | {MODEL}")
    res = {}
    for lv in "ABC":
        r = run(lv); res[lv] = r
        print(f"\n[{lv}] 完全召回@5={r['hits5']}/{len(QUESTIONS)}  @10={r['hits10']}/{len(QUESTIONS)}"
              f"  平均R@5={r['avg5']*100:.1f}%  R@10={r['avg10']*100:.1f}%")

    print("\n\n=== 关键对比（列名完全不透明）===")
    lbl = {'A': 'A 仅代号（dwd_order.f4）', 'B': 'B +中文注释', 'C': 'C +注释+样例值'}
    print(f"{'组':30s} {'完全召回@5':>10s} {'完全召回@10':>11s} {'平均R@10':>9s}")
    for lv in "ABC":
        r = res[lv]
        print(f"{lbl[lv]:30s} {r['hits5']:>7d}/{len(QUESTIONS)} {r['hits10']:>8d}/{len(QUESTIONS)} {r['avg10']*100:8.1f}%")

    print("\n=== 逐题：C 的命中名次（1=第一）===")
    for p in res['C']['per_q']:
        rk = p['rank']
        mark = '✓' if p['r10'] == 1.0 else '✗'
        print(f"  {mark} {p['q'][:20]:22s} 名次={rk}  top1={p['top1']}")

    json.dump(res, open('/tmp/poc8/result_opaque.json', 'w'), ensure_ascii=False, indent=1)
