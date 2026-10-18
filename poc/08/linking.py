"""POC-8：样例值对 schema linking 召回的边际贡献

消融设计（同一批问题、同一模型、同一检索方式）：
  A 组索引 = table.column
  B 组索引 = table.column (TYPE): 中文注释
  C 组索引 = B + 3 个真实样例值

关键：按「列名语义透明度」分组统计，避免用一个平均数掩盖结构性差异。
"""
import json, os, urllib.request, time, statistics, hashlib, math

KEY = os.environ['ZHIPU_KEY']
URL = 'https://open.bigmodel.cn/api/paas/v4/embeddings'
MODEL = 'embedding-3'

# ============ 1. Schema（20 表 / 108 列，企业风格命名） ============
# (table, column, type, comment, samples, transparent)
# transparent=True 表示列名本身能表达业务含义
SCHEMA = [
 ("orders","order_id","BIGINT","订单主键",[], True),
 ("orders","cust_id","BIGINT","客户编号",["C10023","C10088"], False),
 ("orders","order_dt","DATE","下单日期",["2026-09-15","2026-10-01"], True),
 ("orders","status","VARCHAR","订单状态",["completed","refunded","pending","cancelled"], False),
 ("orders","chan_id","INT","渠道编号",["1","3","7"], False),
 ("orders","total_amt","DECIMAL","订单总金额（含税、未扣退款）",["1288.00","356.50"], True),
 ("orders","src_type","VARCHAR","订单来源类型",["app","miniapp","web","offline"], False),
 ("order_items","item_id","BIGINT","明细主键",[], True),
 ("order_items","order_id","BIGINT","所属订单",[], True),
 ("order_items","sku_id","BIGINT","商品编号",["SKU9901"], False),
 ("order_items","qty","INT","购买数量",["1","3","12"], True),
 ("order_items","unit_price","DECIMAL","成交单价",["199.00"], True),
 ("order_items","disc_amt","DECIMAL","优惠金额",["20.00","0.00"], True),
 ("customers","cust_id","BIGINT","客户编号",["C10023"], False),
 ("customers","cust_name","VARCHAR","客户姓名",["张伟","李娜"], True),
 ("customers","reg_dt","DATE","注册日期",["2025-03-11"], True),
 ("customers","seg_lvl","VARCHAR","客户分层等级",["diamond","gold","silver","normal"], False),
 ("customers","home_region_id","INT","归属区域",["3","5"], False),
 ("regions","region_id","INT","区域主键",[], True),
 ("regions","region_name","VARCHAR","大区名称",["华东","华南","华北","西南"], True),
 ("regions","prov_code","VARCHAR","省份编码",["310000","440000"], False),
 ("products","sku_id","BIGINT","商品主键",["SKU9901"], False),
 ("products","sku_name","VARCHAR","商品名称",["无线耳机 Pro"], True),
 ("products","cat_id","INT","所属品类",["12","45"], False),
 ("products","brand_id","INT","所属品牌",["7"], False),
 ("products","list_price","DECIMAL","标价",["299.00"], True),
 ("products","cost_amt","DECIMAL","成本价",["120.00"], True),
 ("categories","cat_id","INT","品类主键",["12"], False),
 ("categories","cat_name","VARCHAR","品类名称",["数码配件","家用电器"], True),
 ("categories","parent_cat_id","INT","上级品类",[], True),
 ("brands","brand_id","INT","品牌主键",["7"], False),
 ("brands","brand_name","VARCHAR","品牌名称",["声学派","清风"], True),
 ("channels","chan_id","INT","渠道主键",["1"], False),
 ("channels","chan_name","VARCHAR","渠道名称",["自营","天猫","京东","抖音","线下门店"], True),
 ("refunds","refund_id","BIGINT","退款单主键",[], True),
 ("refunds","order_id","BIGINT","关联订单",[], True),
 ("refunds","refund_amt","DECIMAL","退款金额",["128.00"], True),
 ("refunds","refund_dt","DATE","退款日期",["2026-09-20"], True),
 ("refunds","reason_code","VARCHAR","退款原因",["quality","wrong_item","no_reason","late"], False),
 ("payments","pay_id","BIGINT","支付流水主键",[], True),
 ("payments","order_id","BIGINT","关联订单",[], True),
 ("payments","pay_method","VARCHAR","支付方式",["alipay","wechat","card","cod"], False),
 ("payments","paid_amt","DECIMAL","实付金额",["1288.00"], True),
 ("payments","paid_at","TIMESTAMP","支付时间",["2026-09-15 14:22:10"], True),
 ("inventory","sku_id","BIGINT","商品编号",["SKU9901"], False),
 ("inventory","wh_id","INT","仓库编号",["2"], False),
 ("inventory","stock_qty","INT","可用库存数量",["0","35","1200"], True),
 ("inventory","snap_dt","DATE","库存快照日期",["2026-10-01"], True),
 ("warehouses","wh_id","INT","仓库主键",["2"], False),
 ("warehouses","wh_name","VARCHAR","仓库名称",["华东仓","华南仓"], True),
 ("warehouses","city_name","VARCHAR","所在城市",["上海","广州"], True),
 ("shipments","ship_id","BIGINT","发货单主键",[], True),
 ("shipments","order_id","BIGINT","关联订单",[], True),
 ("shipments","ship_dt","DATE","发货日期",["2026-09-16"], True),
 ("shipments","carrier","VARCHAR","承运商",["SF","JD","YTO","ZTO"], False),
 ("shipments","dlv_dt","DATE","签收日期",["2026-09-18"], True),
 ("campaigns","camp_id","INT","活动主键",["88"], False),
 ("campaigns","camp_name","VARCHAR","活动名称",["双十一预热","618大促"], True),
 ("campaigns","start_dt","DATE","开始日期",["2026-10-20"], True),
 ("campaigns","end_dt","DATE","结束日期",["2026-11-11"], True),
 ("campaigns","budget_amt","DECIMAL","活动预算",["500000"], True),
 ("camp_events","camp_id","INT","活动编号",["88"], False),
 ("camp_events","stat_dt","DATE","统计日期",["2026-10-21"], True),
 ("camp_events","imp_cnt","BIGINT","曝光次数",["120000"], False),
 ("camp_events","clk_cnt","BIGINT","点击次数",["8600"], False),
 ("camp_events","conv_cnt","BIGINT","转化次数",["320"], False),
 ("camp_events","spend_amt","DECIMAL","花费金额",["23000"], True),
 ("sessions","sess_id","BIGINT","会话主键",[], True),
 ("sessions","cust_id","BIGINT","客户编号",["C10023"], False),
 ("sessions","dev_type","VARCHAR","设备类型",["ios","android","pc","h5"], False),
 ("sessions","start_at","TIMESTAMP","会话开始时间",["2026-10-01 09:12:00"], True),
 ("sessions","dur_sec","INT","会话时长秒",["35","420"], True),
 ("page_views","view_id","BIGINT","浏览主键",[], True),
 ("page_views","sess_id","BIGINT","所属会话",[], True),
 ("page_views","page_url","VARCHAR","页面地址",["/product/9901"], True),
 ("page_views","viewed_at","TIMESTAMP","浏览时间",["2026-10-01 09:13:20"], True),
 ("suppliers","sup_id","INT","供应商主键",["31"], False),
 ("suppliers","sup_name","VARCHAR","供应商名称",["东莞精密制造"], True),
 ("suppliers","contact_name","VARCHAR","联系人",["王强"], True),
 ("purchase_orders","po_id","BIGINT","采购单主键",[], True),
 ("purchase_orders","sup_id","INT","供应商编号",["31"], False),
 ("purchase_orders","sku_id","BIGINT","商品编号",["SKU9901"], False),
 ("purchase_orders","po_qty","INT","采购数量",["500"], True),
 ("purchase_orders","unit_cost","DECIMAL","采购单价",["88.50"], True),
 ("purchase_orders","po_dt","DATE","采购日期",["2026-08-30"], True),
 ("stores","store_id","INT","门店主键",["5"], False),
 ("stores","store_name","VARCHAR","门店名称",["上海静安店"], True),
 ("stores","city_name","VARCHAR","所在城市",["上海"], True),
 ("stores","open_dt","DATE","开业日期",["2024-05-01"], True),
 # 语义不透明列（拼音缩写 / 内部代号）—— 这些是「样例值」真正起作用的地方
 ("orders","xse","DECIMAL","销售额（内部口径，含税）",["1288.00"], False),
 ("orders","djzt","VARCHAR","单据状态（旧系统）",["1","2","9"], False),
 ("order_items","cbl","DECIMAL","成本率",["0.42"], False),
 ("products","tstp","VARCHAR","商品上架标记",["Y","N"], False),
 ("customers","hylx","VARCHAR","会员类型",["A","B","C"], False),
 ("campaigns","tgflag","VARCHAR","投放标记",["1","0"], False),
 ("inventory","aqkc","INT","安全库存",["50"], False),
 ("refunds","tkly","VARCHAR","退款来源",["APP","CS","SYS"], False),
 ("shipments","fhzt","VARCHAR","发货状态",["WAIT","SENT","DONE"], False),
 ("payments","zffs2","VARCHAR","支付方式（二级）",["BAL","POINT","COUPON"], False),
 ("sessions","sb","VARCHAR","设备品牌",["apple","huawei","xiaomi"], False),
 ("products","cpdj","INT","产品等级",["1","2","3"], False),
]

# ============ 2. 问题 + 金标列 ============
# (question, [gold columns], category)
QUESTIONS = [
 ("上月各区域净收入", ["orders.total_amt","regions.region_name","orders.order_dt"], "metric"),
 ("各渠道订单数量", ["channels.chan_name","orders.order_id"], "dimension"),
 ("退款金额最高的品类", ["refunds.refund_amt","categories.cat_name"], "metric"),
 ("客户分层等级分布", ["customers.seg_lvl"], "opaque"),
 ("上月支付方式占比", ["payments.pay_method","payments.paid_amt"], "dimension"),
 ("各仓库可用库存为零的商品", ["inventory.stock_qty","warehouses.wh_name"], "opaque"),
 ("发货后平均几天签收", ["shipments.ship_dt","shipments.dlv_dt"], "metric"),
 ("活动曝光到转化的比例", ["camp_events.imp_cnt","camp_events.conv_cnt"], "metric"),
 ("各设备类型的会话平均时长", ["sessions.dev_type","sessions.dur_sec"], "metric"),
 ("订单来源是 app 的有多少", ["orders.src_type"], "opaque"),
 ("各品牌的标价与成本差", ["brands.brand_name","products.list_price","products.cost_amt"], "metric"),
 ("退款原因为质量问题的订单", ["refunds.reason_code","refunds.order_id"], "opaque"),
 ("采购单价最高的供应商", ["purchase_orders.unit_cost","suppliers.sup_name"], "metric"),
 ("各门店开业时间", ["stores.store_name","stores.open_dt"], "simple"),
 ("商品等级为 1 的销量", ["products.cpdj","order_items.qty"], "opaque"),
 ("承运商是顺丰的发货量", ["shipments.carrier"], "opaque"),
 ("会员类型 A 的客户数", ["customers.hylx"], "opaque"),
 ("各活动预算执行率", ["campaigns.budget_amt","camp_events.spend_amt"], "metric"),
 ("页面浏览到下单的转化", ["page_views.view_id","orders.order_id"], "metric"),
 ("安全库存警戒的商品", ["inventory.aqkc","inventory.sku_id"], "opaque"),
]


def embed(texts, batch=32, retries=3):
    """批量 embedding，带重试"""
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
            except Exception as e:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
    return out


def cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    return dot / (na * nb + 1e-9)


def build_index(level):
    """level: 'A' 仅列名 / 'B' +注释 / 'C' +样例值"""
    texts, keys, meta = [], [], []
    for (t, c, ty, cmt, samples, transparent) in SCHEMA:
        if level == 'A':
            s = f"{t}.{c}"
        elif level == 'B':
            s = f"{t}.{c} ({ty}): {cmt}" if cmt else f"{t}.{c} ({ty})"
        else:
            base = f"{t}.{c} ({ty}): {cmt}" if cmt else f"{t}.{c} ({ty})"
            s = base + (f"; 样例值: {', '.join(samples[:3])}" if samples else "")
        texts.append(s)
        keys.append(f"{t}.{c}")
        meta.append({"transparent": transparent, "has_samples": bool(samples)})
    return texts, keys, meta


def run_level(level):
    texts, keys, meta = build_index(level)
    vecs = embed(texts)
    qvecs = embed([q for q, _, _ in QUESTIONS])

    hits5 = hits10 = 0
    per_q = []
    # 分组统计
    grp = {"transparent": [0, 0], "opaque": [0, 0]}   # [命中, 总数]

    for qi, (q, gold, cat) in enumerate(QUESTIONS):
        scored = [(cosine(qvecs[qi], vecs[i]), keys[i], meta[i]) for i in range(len(keys))]
        scored.sort(key=lambda x: -x[0])
        top10 = [k for _, k, _ in scored[:10]]
        top5 = top10[:5]
        rec5 = len(set(gold) & set(top5)) / len(gold)
        rec10 = len(set(gold) & set(top10)) / len(gold)
        if rec5 == 1.0: hits5 += 1
        if rec10 == 1.0: hits10 += 1
        per_q.append({"q": q, "cat": cat, "gold": gold, "top5": top5,
                      "rec5": rec5, "rec10": rec10})
        # 按金标列的透明度分组
        for g in gold:
            transparent = next((x[5] for x in SCHEMA if f"{x[0]}.{x[1]}" == g), True)
            k = "transparent" if transparent else "opaque"
            grp[k][1] += 1
            if g in top10: grp[k][0] += 1

    avg5 = statistics.mean(p['rec5'] for p in per_q)
    avg10 = statistics.mean(p['rec10'] for p in per_q)
    return {"level": level, "n_cols": len(keys),
            "full_recall_at5": hits5, "full_recall_at10": hits10,
            "avg_recall_at5": avg5, "avg_recall_at10": avg10,
            "group": {k: (v[0], v[1], v[0]/v[1] if v[1] else 0) for k, v in grp.items()},
            "per_q": per_q}


if __name__ == '__main__':
    print(f"schema: {len(SCHEMA)} 列 / {len(QUESTIONS)} 题 | model={MODEL}")
    results = {}
    for lv in "ABC":
        t0 = time.time()
        r = run_level(lv)
        results[lv] = r
        print(f"\n[{lv}] 索引={r['n_cols']} 列  耗时={time.time()-t0:.1f}s")
        print(f"  完全召回@5  {r['full_recall_at5']}/{len(QUESTIONS)}")
        print(f"  完全召回@10 {r['full_recall_at10']}/{len(QUESTIONS)}")
        print(f"  平均 recall@5  = {r['avg_recall_at5']*100:.1f}%")
        print(f"  平均 recall@10 = {r['avg_recall_at10']*100:.1f}%")
        g = r['group']
        print(f"  分组命中率@10:  语义透明列 {g['transparent'][0]}/{g['transparent'][1]} = {g['transparent'][2]*100:.0f}%"
              f"   不透明列 {g['opaque'][0]}/{g['opaque'][1]} = {g['opaque'][2]*100:.0f}%")

    print("\n\n=== 三组对比 ===")
    print(f"{'组':28s} {'R@5':>8s} {'R@10':>8s} {'透明列@10':>10s} {'不透明列@10':>12s}")
    labels = {'A': 'A 仅列名', 'B': 'B +注释', 'C': 'C +注释+样例值'}
    for lv in "ABC":
        r = results[lv]
        g = r['group']
        print(f"{labels[lv]:28s} {r['avg_recall_at5']*100:7.1f}% {r['avg_recall_at10']*100:7.1f}% "
              f"{g['transparent'][2]*100:9.0f}% {g['opaque'][2]*100:11.0f}%")

    # 逐题差异（C vs B）
    print("\n=== C 比 B 改善的题（不透明列相关的）===")
    for pb, pc in zip(results['B']['per_q'], results['C']['per_q']):
        d5 = pc['rec5'] - pb['rec5']
        if d5 > 0.01:
            print(f"  +{d5*100:5.0f}pp  {pc['q'][:22]:24s} B={pb['rec5']*100:3.0f}% C={pc['rec5']*100:3.0f}%")

    json.dump(results, open('/tmp/poc8/result.json', 'w'), ensure_ascii=False, indent=1)
    print("\n保存 /tmp/poc8/result.json")
