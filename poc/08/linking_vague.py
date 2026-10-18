"""POC-8c：注释模糊时，样例值能否救回？

v2 的注释写得过于完整（"订单应付总额（含税，未扣退款）"），
真实企业数据仓库的注释往往是"状态""金额""类型"甚至为空。

四组对照（同一批 35 列 / 20 题）：
  A 仅代号                t.f5
  B 模糊注释              t.f5: 状态
  C 模糊注释 + 样例值      t.f5: 状态; 常见取值 completed, refunded, pending, cancelled
  D 仅样例值（无注释）      t.f5: 常见取值 completed, refunded, pending, cancelled
"""
import json, os, urllib.request, time, statistics, math

KEY = os.environ['ZHIPU_KEY']
URL = 'https://open.bigmodel.cn/api/paas/v4/embeddings'
MODEL = 'embedding-3'

# (table, col, vague_comment, samples)
COLS = [
 ("dwd_order","f1","编号",["90000123","90000124"]),
 ("dwd_order","f2","编号",["C10023","C10088"]),
 ("dwd_order","f3","日期",["2026-09-15","2026-10-01"]),
 ("dwd_order","f4","金额",["1288.00","356.50"]),
 ("dwd_order","f5","状态",["completed","refunded","pending","cancelled"]),
 ("dwd_order","f6","编号",["1","3","7"]),
 ("dwd_order","attr_01","类型",["app","miniapp","web","offline"]),
 ("dwd_order","xse","金额",["1288.00"]),
 ("dwd_order","djzt","状态",["1","2","9"]),
 ("dwd_cust","v1","编号",["C10023"]),
 ("dwd_cust","v2","名称",["张伟","李娜"]),
 ("dwd_cust","v3","日期",["2025-03-11"]),
 ("dwd_cust","v4","类型",["diamond","gold","silver","normal"]),
 ("dwd_cust","hylx","类型",["A","B","C"]),
 ("dwd_cust","v5","编号",["3","5"]),
 ("dwd_prod","p1","编号",["SKU9901"]),
 ("dwd_prod","p2","名称",["无线耳机 Pro"]),
 ("dwd_prod","p3","金额",["299.00"]),
 ("dwd_prod","p4","金额",["120.00"]),
 ("dwd_prod","cpdj","等级",["1","2","3"]),
 ("dwd_prod","tstp","标记",["Y","N"]),
 ("dwd_refund","r1","编号",["77001"]),
 ("dwd_refund","r2","编号",["90000123"]),
 ("dwd_refund","r3","金额",["128.00"]),
 ("dwd_refund","r4","日期",["2026-09-20"]),
 ("dwd_refund","r5","原因",["quality","wrong_item","no_reason","late"]),
 ("dwd_refund","tkly","来源",["APP","CS","SYS"]),
 ("dwd_ship","s1","编号",["66001"]),
 ("dwd_ship","s2","编号",["90000123"]),
 ("dwd_ship","s3","日期",["2026-09-16"]),
 ("dwd_ship","s4","编码",["SF","JD","YTO","ZTO"]),
 ("dwd_ship","s5","日期",["2026-09-18"]),
 ("dwd_ship","fhzt","状态",["WAIT","SENT","DONE"]),
 ("dwd_inv","i3","数量",["0","35","1200"]),
 ("dwd_inv","aqkc","数量",["50"]),
]

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
                out.extend([x['embedding'] for x in d['data']]); break
            except Exception:
                if attempt == retries - 1: raise
                time.sleep(2 ** attempt)
    return out


def cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x*x for x in a)) * math.sqrt(sum(x*x for x in b)) + 1e-9)


def text_for(t, c, cmt, samples, level):
    if level == 'A': return f"{t}.{c}"
    if level == 'B': return f"{t}.{c}: {cmt}"
    if level == 'C': return f"{t}.{c}: {cmt}; 常见取值 {', '.join(samples)}"
    return f"{t}.{c}: 常见取值 {', '.join(samples)}"   # D 仅样例值


def run(level):
    labels = [text_for(*row, level) for row in COLS]
    keys = [f"{r[0]}.{r[1]}" for r in COLS]
    vecs = embed(labels)
    qvecs = embed([q for q, _ in QUESTIONS])
    per_q, h5, h10 = [], 0, 0
    for qi, (q, gold) in enumerate(QUESTIONS):
        sc = sorted(((cosine(qvecs[qi], v), k) for v, k in zip(vecs, keys)), reverse=True)
        top10 = [k for _, k in sc[:10]]
        r5 = len(set(gold) & set(top10[:5])) / len(gold)
        r10 = len(set(gold) & set(top10)) / len(gold)
        h5 += (r5 == 1.0); h10 += (r10 == 1.0)
        per_q.append({"q": q, "r5": r5, "r10": r10,
                      "rank": [top10.index(g)+1 if g in top10 else None for g in gold]})
    return {"level": level, "h5": h5, "h10": h10,
            "avg5": statistics.mean(p['r5'] for p in per_q),
            "avg10": statistics.mean(p['r10'] for p in per_q), "per_q": per_q}


if __name__ == '__main__':
    print(f"{len(COLS)} 列 / {len(QUESTIONS)} 题 | {MODEL}")
    res = {}
    for lv in "ABCD":
        r = run(lv); res[lv] = r
        print(f"[{lv}] 完全@5={r['h5']}/20  @10={r['h10']}/20  平均R@5={r['avg5']*100:5.1f}%  R@10={r['avg10']*100:5.1f}%")

    lbl = {'A':'A 仅代号','B':'B 模糊注释','C':'C 模糊注释+样例值','D':'D 仅样例值'}
    print(f"\n{'组':24s} {'完全@5':>7s} {'完全@10':>8s} {'R@5':>7s} {'R@10':>7s}")
    for lv in "ABCD":
        r = res[lv]
        print(f"{lbl[lv]:24s} {r['h5']:>4d}/20 {r['h10']:>5d}/20 {r['avg5']*100:6.1f}% {r['avg10']*100:6.1f}%")

    print("\n=== 边际贡献（相对上一组）===")
    print(f"  注释的作用（B-A）:      R@10 {res['B']['avg10']*100 - res['A']['avg10']*100:+.1f}pp")
    print(f"  样例值的作用（C-B）:    R@10 {res['C']['avg10']*100 - res['B']['avg10']*100:+.1f}pp")
    print(f"  样例值单独（D-A）:      R@10 {res['D']['avg10']*100 - res['A']['avg10']*100:+.1f}pp")
    print(f"  注释+样例 vs 仅样例（C-D）: R@10 {res['C']['avg10']*100 - res['D']['avg10']*100:+.1f}pp")

    json.dump(res, open('/tmp/poc8/result_vague.json','w'), ensure_ascii=False, indent=1)
