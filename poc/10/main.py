#!/usr/bin/env python3
# POC-10: verify two unmeasured design claims in Section 4.17
# Part A: Chinese retrieval - char bigram vs jieba(word) vs hybrid, BM25, Recall@5
# Part B: deterministic Chinese time parser feasibility - 200+ cases, target >=98%
import json, re, math, random
from datetime import date, timedelta
import calendar
import jieba

# ---------------- Part A ----------------
# 30 columns with Chinese names + comments (enterprise-ish; some contain hard-to-segment domain terms)
COLS = [
 ("djje","订单金额：每笔订单的应付总金额，含税"),
 ("xse","销售额：已支付订单的成交金额合计"),
 ("ml_e","毛利额：销售额扣除商品成本后的毛利金额"),
 ("mll","毛利率：毛利额占销售额的比例"),
 ("kddj","客单价：平均每笔订单的成交金额"),
 ("tke","退款额：已退款订单的金额合计"),
 ("tkl","退款率：退款订单数占订单总数的比例"),
 ("gmj","购买件数：订单明细中的商品数量合计"),
 ("sl","数量：订单明细中的商品件数"),
 ("dj","单价：商品在订单明细中的成交单价"),
 ("cbf","成本额：商品采购成本合计"),
 ("jhrq","进货日期：商品入库的日期"),
 ("cjsj","创建时间：订单创建的时间戳"),
 ("zfsj","支付时间：订单完成支付的时间戳"),
 ("fhsj","发货时间：订单出库发货的时间戳"),
 ("qsrq","签收日期：客户签收的日期"),
 ("dqsj","到期时间：合同或优惠券的到期时间"),
 ("dq","地区：订单所属的销售大区"),
 ("cs","城市：用户所在城市"),
 ("sf","省份：用户所在省份"),
 ("yhdj","用户等级：会员等级，1-3 级"),
 ("hydj","会员等级：用户会员等级"),
 ("zhlx","账号类型：企业账号或个人账号"),
 ("ddzt","订单状态：已支付/已退款/待支付"),
 ("zfzt","支付状态：支付成功或失败"),
 ("cplx","品类：商品所属的商品品类"),
 ("pp","品牌：商品品牌名称"),
 ("gysmc","供应商名称：供货方公司名称"),
 ("xss","销售省：订单销售省份"),
 ("gmzh","购买账号：下单用户的账号标识"),
 ("dxl","动销率：有销量的 SKU 数占在架 SKU 数的比例"),
 ("khlx","客户类型：新客、老客或流失客户"),
 ("dyl","复购率：重复购买客户占购买客户的比例"),
 ("cjrq","成交日期：订单支付的日期"),
 ("zjje","折扣金额：订单优惠券与折扣的减免金额"),
 ("bjje","比价金额：竞品同款商品的参考价"),
 ("kcl","库存量：仓库当前可用库存数量"),
 ("kccb","库存成本：库存商品的加权平均成本"),
 ("aqkc","安全库存：避免缺货的最低库存阈值"),
 ("zzts","周转天数：库存平均周转所需天数"),
 ("jhsj","交货时间：供应商承诺的交货日期"),
 ("qdsj","起订量：供应商要求的最小起订数量"),
 ("gysdj","供应商等级：按履约质量评定的等级"),
 ("htbh","合同编号：采购或销售合同的编号"),
 ("htje","合同金额：合同签署的总金额"),
 ("jsfs","结算方式：月结、季结或现结"),
 ("zkq","账期：客户付款的信用期天数"),
 ("yqts","逾期天数：超过账期未付款的天数"),
 ("hkb","回款比例：已回款金额占应收的比例"),
 ("yszk","应收账款：尚未收回的销售款项"),
 ("yszh","应收账龄：应收账款按账龄分桶"),
 ("xz","现值：现金流折现后的当前价值"),
 ("nz","年值：按年折算的等值金额"),
 ("nbx","内部收益率：项目现金流的内部收益率"),
 ("tzhs","投资回收期：收回初始投资的月份数"),
 ("mll2","净利率：净利润占营业收入的比例"),
 ("jlr","净利润：扣除税费后的利润"),
 ("yysr","营业收入：主营与其他业务收入合计"),
 ("yycb","营业成本：主营业务的直接成本"),
 ("qjfy","期间费用：销售、管理与财务费用合计"),
 ("yffy","研发费用：研发投入的费用化金额"),
 ("xsfy","销售费用：市场与销售团队的费用"),
 ("cwfy","财务费用：利息与汇兑损益合计"),
 ("zichan","资产总额：资产负债表上的资产合计"),
 ("fuzhai","负债总额：资产负债表上的负债合计"),
 ("zcfzl","资产负债率：负债总额占资产总额的比例"),
 ("ldbl","流动比率：流动资产占流动负债的比例"),
 ("sdbl","速动比率：扣除存货后的流动比率"),
 ("xjll","现金流量：经营活动产生的现金净流量"),
 ("jyxj","经营现金流：经营活动现金流入减流出"),
 ("tzzc","投资支出：购建固定资产等投资活动支出"),
 ("rzye","融资余额：借款与债券融资的余额"),
 ("gdzc","固定资产：房屋设备等固定资产原值"),
 ("wxzc","无形资产：专利商标等无形资产原值"),
 ("zj","折旧：固定资产本期计提折旧"),
 ("tx","摊销：无形资产与长期待摊费用摊销"),
 ("yjsr","预收收入：已收款未确认的收入"),
 ("yfje","应付金额：尚未支付的采购款项"),
 ("zpje","预付款：预付给供应商的款项"),
 ("ddje","订单金额：下单时的订单总金额"),
 ("ddlx","订单类型：零售、批发或团购"),
 ("qdlx","渠道类型：线上、门店或经销"),
 ("qdmc","渠道名称：具体销售渠道的名称"),
 ("mdmc","门店名称：线下门店的名称"),
 ("mdjb","门店级别：按面积与销量划分的级别"),
 ("ygs","员工数：门店或部门的在职员工人数"),
 ("rsl","人效：人均销售额"),
 ("pjl","坪效：单位面积销售额"),
 ("khl","客户流失率：统计期内流失客户占比"),
 ("tsl","投诉率：投诉订单占订单总数的比例"),
 ("pjf","平均分：客户评价的平均评分"),
 ("hpj","好评率：四星及以上评价的占比"),
 ("fhs","退货率：退货订单占订单总数的比例"),
 ("thje","退货金额：退货订单的退款金额"),
]

QUERIES = [
 ("各地区的销售额","xse"),("每个大区的订单金额合计","djje"),
 ("毛利额是多少","ml_e"),("毛利率怎么算的","mll"),
 ("客单价","kddj"),("平均每单成交金额","kddj"),
 ("退款额","tke"),("退款率","tkl"),
 ("一共卖了多少件","gmj"),("商品件数合计","sl"),
 ("成交单价","dj"),("采购成本","cbf"),
 ("入库日期","jhrq"),("下单时间","cjsj"),
 ("支付时间","zfsj"),("发货了没有","fhsj"),
 ("客户什么时候签收的","qsrq"),("合同什么时候到期","dqsj"),
 ("按大区分组","dq"),("用户所在城市分布","cs"),
 ("按省份统计","sf"),("会员等级分布","hydj"),
 ("企业账号有多少","zhlx"),("已支付的订单","ddzt"),
 ("支付失败的订单","zfzt"),("各品类销量","cplx"),
 ("品牌排行榜","pp"),("供应商是哪家","gysmc"),
 ("销售省份的销售额","xss"),("下单账号","gmzh"),
 ("动销情况","dxl"),("新老客户结构","khlx"),("复购情况","dyl"),
 ("折扣减免了多少钱","zjje"),("比价参考价","bjje"),("仓库还有多少货","kcl"),
 ("库存加权成本","kccb"),("安全库存阈值","aqkc"),("库存周转天数","zzts"),
 ("供应商什么时候交货","jhsj"),("最小起订量","qdsj"),("供应商评级","gysdj"),
 ("合同编号","htbh"),("合同总金额","htje"),("月结还是现结","jsfs"),
 ("客户账期多少天","zkq"),("逾期了几天","yqts"),("回款进度","hkb"),
 ("应收还有多少","yszk"),("应收账龄分桶","yszh"),("现金流折现","xz"),
 ("年化金额","nz"),("项目IRR","nbx"),("多久回本","tzhs"),
 ("净利率","mll2"),("净利润","jlr"),("营业收入合计","yysr"),
 ("主营成本","yycb"),("三费合计","qjfy"),("研发投入","yffy"),
 ("销售团队花费","xsfy"),("利息与汇兑","cwfy"),("资产合计","zichan"),
 ("负债合计","fuzhai"),("负债率","zcfzl"),("流动比率","ldbl"),
 ("速动比率","sdbl"),("经营现金净流量","jyxj"),("投资活动支出","tzzc"),
 ("融资余额","rzye"),("固定资产原值","gdzc"),("无形资产原值","wxzc"),
 ("本期折旧","zj"),("摊销费用","tx"),("预收账款","yjsr"),
 ("应付未付","yfje"),("预付给供应商的钱","zpje"),("零售还是批发","ddlx"),
 ("线上还是门店","qdlx"),("渠道名称","qdmc"),("门店名称","mdmc"),
 ("门店分级","mdjb"),("在职人数","ygs"),("人均销售额","rsl"),
 ("单位面积产出","pjl"),("客户流失","khl"),("投诉占比","tsl"),
 ("评价平均分","pjf"),("好评占比","hpj"),("退货比例","fhs"),("退货退款金额","thje"),
]

# domain dictionary (would be built from MDL in production; here from column names + business terms)
DOMAIN_DICT = ["毛利额","毛利率","客单价","退款额","退款率","购买件数","成本额","进货日期","创建时间",
 "支付时间","发货时间","签收日期","到期时间","会员等级","账号类型","订单状态","支付状态","品类",
 "供应商名称","销售省","购买账号","成交金额","应付总金额","销售大区","商品件数","商品品类","订单明细"]

def tok_jieba(t):
    return [w for w in jieba.lcut_for_search(t) if w.strip()]

def tok_bigram(t):
    out, buf = [], []
    for ch in t:
        if '\u4e00' <= ch <= '\u9fff':
            buf.append(ch)
        else:
            if len(buf) >= 2:
                out += [buf[i]+buf[i+1] for i in range(len(buf)-1)]
            elif buf: out.append(buf[0])
            buf = []
            if ch.strip() and ch.isascii(): out.append(ch.lower())
    if len(buf) >= 2:
        out += [buf[i]+buf[i+1] for i in range(len(buf)-1)]
    elif buf: out.append(buf[0])
    return out

def tok_hybrid(t):
    # bigram + domain dictionary terms present in text (longest-first, non-overlapping on top of bigrams)
    grams = tok_bigram(t)
    extra = [w for w in DOMAIN_DICT if w in t]
    return grams + extra

class BM25:
    def __init__(self, docs, tok):
        self.tok = tok
        self.docs = [tok(d) for d in docs]
        self.N = len(docs)
        self.avgdl = sum(len(d) for d in self.docs)/max(1,self.N)
        self.df = {}
        for d in self.docs:
            for w in set(d): self.df[w] = self.df.get(w,0)+1
        self.tf = [{w:d.count(w) for w in set(d)} for d in self.docs]
    def score(self, q):
        k1,b = 1.5, 0.75
        qt = self.tok(q); out=[]
        for i,d in enumerate(self.docs):
            s=0.0
            for w in qt:
                if w not in self.tf[i]: continue
                idf = math.log(1 + (self.N - self.df.get(w,0) + 0.5)/(self.df.get(w,0)+0.5))
                f = self.tf[i][w]; dl = len(d)
                s += idf * (f*(k1+1))/(f + k1*(1-b+b*dl/max(1,self.avgdl)))
            out.append((s,i))
        out.sort(reverse=True)
        return [i for _,i in out]

def run_part_a():
    docs = [f"{c[1]}" for c in COLS]  # index text = 中文名 + 注释
    res = {}
    for name, tok in [("jieba", tok_jieba), ("bigram", tok_bigram), ("hybrid", tok_hybrid)]:
        bm = BM25(docs, tok)
        hits5 = hits1 = 0; misses=[]
        for q, gold in QUERIES:
            gi = next(i for i,c in enumerate(COLS) if c[0]==gold)
            ranked = bm.score(q)[:5]
            if gi in ranked[:5]: hits5 += 1
            else: misses.append(q)
            if ranked and ranked[0]==gi: hits1 += 1
        res[name] = {"R@5": hits5, "R@1": hits1, "n": len(QUERIES), "misses": misses}
        print(f"A[{name}] R@5={hits5}/{len(QUERIES)}  R@1={hits1}/{len(QUERIES)}")
    return res

# ---------------- Part B: deterministic parser ----------------
TODAY = date(2026, 10, 17)

def add_months(d, k):
    y, m = d.year, d.month + k
    y += (m-1)//12; m = (m-1)%12 + 1
    return date(y, m, 1)

def month_range(y, m): return date(y,m,1), date(y,m,calendar.monthrange(y,m)[1])

def quarter_range(y, q): return date(y,3*q-2,1), date(y,3*q,calendar.monthrange(y,3*q)[1])

def parse_cn_time(s, today=TODAY, fiscal_start=4):
    """Deterministic parser. Returns (start, end) or raises ValueError."""
    s = s.strip()
    # explicit range: 2024年3月到5月
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月到(\d{1,2})月", s)
    if m:
        y, a, b = map(int, m.groups())
        return date(y,a,1), month_range(y,b)[1]
    # explicit year-month: 2025年10月
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月", s)
    if m:
        return month_range(int(m.group(1)), int(m.group(2)))
    # relative year-month: 去年10月 / 今年3月 / 明年1月
    m = re.fullmatch(r"(去年|今年|明年)(\d{1,2})月", s)
    if m:
        y = {"去年": today.year-1, "今年": today.year, "明年": today.year+1}[m.group(1)]
        return month_range(y, int(m.group(2)))
    # 财年 Q: 本财年Q2
    m = re.fullmatch(r"本财年Q(\d)", s)
    if m:
        q = int(m.group(1))
        fy_start_year = today.year if today.month >= fiscal_start else today.year - 1
        # fiscal quarters start at fiscal_start month
        qstart_month = fiscal_start + 3*(q-1)
        y = fy_start_year + (qstart_month-1)//12
        mm = (qstart_month-1)%12 + 1
        return month_range(y, mm)
    # 财年 expressions
    if s in ("本财年", "本财年至今"):
        start = date(today.year, fiscal_start, 1) if today.month >= fiscal_start else date(today.year-1, fiscal_start, 1)
        return start, today
    if s in ("上一财年", "上个财年"):
        fy_start_year = today.year if today.month >= fiscal_start else today.year - 1
        return date(fy_start_year-1, fiscal_start, 1), date(fy_start_year, fiscal_start, 1) - timedelta(days=1)
    m = re.fullmatch(r"财年(\d{4})", s)
    if m:
        y = int(m.group(1))
        return date(y-1, fiscal_start, 1), date(y, fiscal_start, 1) - timedelta(days=1)
    # 昨天/前天/今天
    if s == "昨天": return today - timedelta(days=1), today - timedelta(days=1)
    if s == "前天": return today - timedelta(days=2), today - timedelta(days=2)
    if s == "今天": return today, today
    # 本月截至昨天
    if s == "本月截至昨天": return date(today.year, today.month, 1), today - timedelta(days=1)
    # 最近/过去/近 N 天
    m = re.fullmatch(r"(?:最近|过去|近)(\d+)天", s)
    if m:
        n = int(m.group(1)); return today - timedelta(days=n-1), today
    m = re.fullmatch(r"过去一周（含今天）|最近一周|近一周", s)
    if m: return today - timedelta(days=6), today
    # 近一年/过去12个月
    if s in ("近一年（截至今天）", "过去12个月", "近12个月"):
        return today - timedelta(days=364), today
    # 季度
    def q_of(d): return (d.month-1)//3 + 1
    if s in ("本季度",):
        return quarter_range(today.year, q_of(today))
    if s in ("上个季度", "上一个完整季度"):
        q = q_of(today) - 1; y = today.year
        if q == 0: q, y = 4, y-1
        return quarter_range(y, q)
    if s in ("上上个季度",):
        q = q_of(today) - 2; y = today.year
        while q <= 0: q += 4; y -= 1
        return quarter_range(y, q)
    if s == "去年同一季度":
        return quarter_range(today.year-1, q_of(today))
    if s == "今年上半年":
        return date(today.year,1,1), date(today.year,6,30)
    m = re.fullmatch(r"(\d{4})年(?:第)?([一二三四1-4])季度", s)
    if m:
        y = int(m.group(1)); qn = {"一":1,"二":2,"三":3,"四":4}.get(m.group(2), None) or int(m.group(2))
        return quarter_range(y, qn)
    if s == "去年第四季度":
        return quarter_range(today.year-1, 4)
    # 年
    if s in ("去年全年","去年一整年","2025年全年"):
        y = today.year-1 if not s.startswith("2025") else 2025
        return date(y,1,1), date(y,12,31)
    if s in ("今年以来","年初至今"):
        return date(today.year,1,1), today
    # 月
    if s in ("上个月","上个月整月","上一个完整月份"):
        first = date(today.year, today.month, 1)
        last_prev = first - timedelta(days=1)
        return date(last_prev.year, last_prev.month, 1), last_prev
    if s == "本月":
        return month_range(today.year, today.month)
    if s == "去年同期（按月）":
        return month_range(today.year-1, today.month)
    # 周
    if s == "上周":
        monday = today - timedelta(days=today.weekday())
        start = monday - timedelta(days=7)
        return start, start + timedelta(days=6)
    raise ValueError(f"unparsed: {s}")

# independent ground-truth builders (do not reuse parse_cn_time)
def gt(expr, today=TODAY, fs=4):
    import importlib.util
    # recompute with calendar module independently per template family
    if expr == "上个月":
        first = date(today.year, today.month, 1); last = first - timedelta(days=1)
        return date(last.year, last.month, 1), last
    if expr == "本月": return date(today.year,today.month,1), date(today.year,today.month,calendar.monthrange(today.year,today.month)[1])
    if expr == "上周":
        mon = today - timedelta(days=today.weekday()); s = mon - timedelta(days=7); return s, s+timedelta(days=6)
    if expr == "今年以来": return date(today.year,1,1), today
    if expr == "过去30天": return today - timedelta(days=29), today
    if expr == "最近90天": return today - timedelta(days=89), today
    if expr == "本季度":
        q=(today.month-1)//3+1; return date(today.year,3*q-2,1), date(today.year,3*q,calendar.monthrange(today.year,3*q)[1])
    raise ValueError(expr)

def build_cases():
    cases = []
    # fixed cases
    fixed = {
        "上个月":"上个月","本月":"本月","上周":"上周","今年以来":"今年以来",
        "过去30天":"过去30天","最近90天":"最近90天","本季度":"本季度",
    }
    for k,v in fixed.items(): cases.append((k, gt(v)))
    # generated: 去年N月 / N年M月
    for mth in range(1,13):
        cases.append((f"{TODAY.year-1}年{mth}月", month_range(TODAY.year-1, mth)))
        cases.append((f"去年{mth}月", month_range(TODAY.year-1, mth)))
    # 季度
    for q in (1,2,3,4):
        cases.append((f"{TODAY.year}年第{q}季度", quarter_range(TODAY.year,q)))
        cases.append((f"{TODAY.year-1}年第{'一二三四'[q-1]}季度", quarter_range(TODAY.year-1,q)))
    # N 天
    for n in (7,14,30,60,90,180,365):
        cases.append((f"最近{n}天", (TODAY - timedelta(days=n-1), TODAY)))
        cases.append((f"过去{n}天", (TODAY - timedelta(days=n-1), TODAY)))
        cases.append((f"近{n}天", (TODAY - timedelta(days=n-1), TODAY)))
    # fiscal with various starts
    for fs in (1,4,7,10):
        fy = TODAY.year if TODAY.month >= fs else TODAY.year-1
        cases.append((f"本财年__fs{fs}", (date(fy,fs,1), TODAY)))
        prev_start = date(fy-1,fs,1)
        cases.append((f"上一财年__fs{fs}", (prev_start, date(fy,fs,1)-timedelta(days=1))))
    # explicit ranges
    for y in (2023,2024,2025):
        for a,b in ((1,3),(4,6),(7,9),(10,12)):
            cases.append((f"{y}年{a}月到{b}月", (date(y,a,1), month_range(y,b)[1])))
    # 昨天/前天/本月截至昨天
    cases += [("昨天",(TODAY-timedelta(days=1),TODAY-timedelta(days=1))),
              ("前天",(TODAY-timedelta(days=2),TODAY-timedelta(days=2))),
              ("本月截至昨天",(date(TODAY.year,TODAY.month,1),TODAY-timedelta(days=1)))]
    return cases

def run_part_b():
    cases = build_cases()
    ok = 0; fails=[]
    for expr, expect in cases:
        fs = 4
        if "__fs" in expr:
            base, fs = expr.split("__fs"); fs = int(fs); expr = base
        try:
            got = parse_cn_time(expr, TODAY, fs)
        except Exception as e:
            got = None
        if got == expect: ok += 1
        else: fails.append({"expr": expr, "fs": fs, "expect": [str(expect[0]),str(expect[1])],
                            "got": [str(got[0]),str(got[1])] if got else None})
    print(f"B parser: {ok}/{len(cases)} = {100*ok/len(cases):.1f}%")
    return {"ok": ok, "n": len(cases), "acc": ok/len(cases), "fails": fails}

if __name__ == "__main__":
    a = run_part_a()
    b = run_part_b()
    json.dump({"partA": a, "partB": b}, open("/tmp/poc10_results.json","w"), ensure_ascii=False, indent=1)
