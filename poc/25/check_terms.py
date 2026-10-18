#!/usr/bin/env python3
# POC-25 v2: docs terminology lint against the canonical naming scheme
import re, sys, json

FILES = {
  "whitepaper": "/workspace/text2charts-whitepaper/产品白皮书.md",
  "tech": "/workspace/text2charts-whitepaper/技术设计方案.md",
}

RULES = [
  ("CACHE_AMBIG", "缓存层级应为 C1/C2", r"L[12]\s*缓存|缓存\s*L[12]"),
  ("BIND_AMBIG", "绑定层级应为 B0/B1/B2", r"L[012]\s*(路径|绑定)|三级绑定.{0,12}L[012]"),
  ("FILL_AMBIG", "Fill 扩展点应为 Fill-1/2/3", r"L[1-3]\s*(声明式|函数钩子|替换)"),
  ("HITL_AMBIG", "HITL 分级应为 H1..H4", r"L[1-4]\s*(事后纠错|事前确认|拒绝执行|自动执行)"),
  ("TASK_AMBIG", "任务层应为 A1/A2/A3", r"L[1-3]\s+(NL2SQL|Data2Charts|NL2Charts)"),
  ("EVAL_ROW_AMBIG", "评测矩阵行应为 E1/E2/E3", r"^\|\s*\**L(1\.5|[123])\**\s*\|"),
  ("DIALECT_GATE_AMBIG", "方言门禁应为 DG1–DG9",
   r"门禁[^。\n]{0,10}\bD[1-9]\b|\bD[1-9]\s*(探针表|查询差分|编译期解析|跨层缓存等价|版本升级)"),
  ("FED_GATE_AMBIG", "联邦门禁应为 FG1–FG8",
   r"\bF[1-8]\s*(附加与时延|下推证据|只读|快照一致性|类型映射|浏览器降级|凭证泄漏)|门禁\s*F[1-8]"),
  ("ASSERT_LEVEL_AMBIG", "断言级别用 A1–A4（应为 AS1–AS4，A1–A3 是任务层）",
   r"A[1-4]\s*(空结果|grain|不变量|基数上限)"),
  ("UX_GATE_AMBIG", "连接器 UX 门禁应为 UX1–UX6", r"^\|\s*C[1-6]\s*\|"),
  ("BARE_L_IN_TABLE", "表格首列禁止裸 L0–L3", r"^\|\s*\**L[0-3](\.5)?\**\s*\|\s*[^\s]"),
  # ---- v4.37 命名基线（ADR-106）----
  ("PKG_OLD_SCOPE", "旧 scope @t2c 已废弃", r"@t2c/"),
  ("PKG_BARE_SCOPE", "scope 下的包必须带 nl2charts- 前缀", r"@agentix-e/(?!nl2charts[-\s`）)]|nl2charts$)"),
  ("PKG_NL2SQL_PKG", "nl2sql 只能作能力名，不能作包名", r"@agentix-e/nl2charts-nl2sql"),
  ("PKG_ASK_ALIAS", "ask 是废弃别名，入口包为 nl2charts-core", r"@agentix-e/(nl2charts-)?ask\b"),
  ("OLD_IDENT", "旧产品标识 t2c 已废弃", r"(?i)(?<![a-z])t2c(?![a-z])"),
]

def scan():
  report = {}
  for name, path in FILES.items():
    lines = open(path, encoding="utf-8").read().splitlines()
    hits = []
    for rid, desc, pat in RULES:
      rx = re.compile(pat)
      for i, line in enumerate(lines, 1):
        # 豁免：术语表"禁止写法"列（反引号内的反例）与 POC-25 的元文档行
        if re.search(r'`[^`]*(L[0-3]|D[1-9]|F[1-8]|C[1-6])[^`]*`', line): continue
        if re.match(r'^\|\s*(缓存层级用|方言门禁用|联邦门禁用|连接器门禁用|任务层用|评测矩阵行用|Fill 扩展点用|HITL 用|表格裸)', line): continue
        # 豁免：文档中"故意写错的反例"与"修正旧表述"的历史引用
        if rid == "PKG_BARE_SCOPE" and re.search(r'必须红|反例|撞名|判红|违反的症状|startsWith\(`?@agentix-e/nl2charts-', line): continue
        if rid == "PKG_NL2SQL_PKG" and re.search(r'判红|不得再作为包名|反例', line): continue
        if rid == "OLD_IDENT" and re.search(r'旧表述|修正 v4|废弃', line): continue
        if rx.search(line):
          hits.append({"rule": rid, "line": i, "text": line.strip()[:160]})
    report[name] = hits
  return report

if __name__ == "__main__":
  rep = scan(); total = 0
  for name, hits in rep.items():
    print(f"== {name}: {len(hits)} violations")
    by = {}
    for h in hits:
      by[h["rule"]] = by.get(h["rule"], 0) + 1
      print(f"   {h['rule']:<20} L{h['line']:<5} {h['text'][:110]}")
    for k, v in sorted(by.items()): print(f"   -> {k}: {v}")
    total += len(hits)
  print("TOTAL", total)
  json.dump(rep, open("/tmp/poc25_report.json", "w"), ensure_ascii=False, indent=1)
  sys.exit(1 if total else 0)
