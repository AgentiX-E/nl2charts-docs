"""POC-30B: 消融——把业务口径写进 prompt 能消掉多少错误"""
import json, re, collections, time, sys
sys.path.insert(0, '/tmp/poc30')
from main import build_db, rows_of, multiset, call, clean_sql, SCHEMA_CARD, Q

RULES = """
Business rules (authoritative):
- `discount` is a FRACTION in [0,1] applied to that line: net = qty * unit_price * (1 - discount).
- An order is "refunded" iff orders.status = 'refunded'. The `refunds` table stores individual refund
  events and does NOT cover every refunded order; do not infer order status from it.
- "Revenue" always means sum of net line amounts (qty*unit_price*(1-discount)); use orders.total_amount
  only when the question is about order-level totals.
- Percentages may be returned as a fraction in [0,1]; do not multiply by 100 unless asked for "percent".
- For quarter, return the quarter number (1-4), not a date.
"""

PROMPT2 = """You are a SQL expert. Translate the question into a single DuckDB SQL query.

{schema}
{rules}
Rules:
- Output ONLY the SQL, no explanation, no markdown fences.
- Use only the tables/columns above.
- Return exactly the columns the question asks for; do not add identifier columns unless required.

Question: {q}
SQL:"""

ADJ = {'q09', 'q16', 'q23', 'q26', 'q27', 'q28'}   # 来自 POC-30 的裁定

if __name__ == '__main__':
    con = build_db()
    out = []
    t0 = time.time()
    for qid, qtext, cat, gold in Q:
        g, e = rows_of(con, gold); assert e is None
        runs = []
        for _ in range(3):
            txt, dt, tok, err = call(PROMPT2.format(schema=SCHEMA_CARD, rules=RULES, q=qtext))
            sql = clean_sql(txt)
            rr, e2 = rows_of(con, sql) if sql else (None, 'empty_output')
            runs.append({'sql': sql, 'rows': rr, 'err': e2 or err})
        key = lambda r: re.sub(r'\s+', ' ', (r['sql'] or '').lower()).strip()
        votes = collections.Counter(key(r) for r in runs if r['rows'] is not None)
        if votes:
            wk, nv = votes.most_common(1)[0]; ch = next(r for r in runs if key(r) == wk)
        else:
            ch = runs[0]; nv = 0
        ok_strict = ch['rows'] is not None and multiset(g) == multiset(ch['rows'])
        # 宽松：忽略额外列，按"每题期望列数"对齐比较（仅用于裁定辅助，正式仍以严格为准）
        rec = {'id': qid, 'cat': cat, 'strict': ok_strict, 'agree': f'{nv}/3',
               'sql': ch['sql'], 'err': ch['err'],
               'gold_rows': len(g), 'pred_rows': len(ch['rows']) if ch['rows'] is not None else None}
        out.append(rec)
        print(f"  {qid} {cat:<20} strict={ok_strict} agree={rec['agree']}")

    strict = sum(1 for r in out if r['strict'])
    # 用同一套裁定集合（POC-30 已逐条看过）的"语义正确"重算：本臂若严格通过则一定语义正确
    print('\n=== 对比 ===')
    base = json.load(open('/tmp/poc30_results.json'))
    b_strict = base['correct']
    b_adj = sum(1 for r in base['details'] if r['ok'] or r['id'] in ADJ)
    print(f'baseline  strict {b_strict}/30={b_strict/30:.3f}  adjudicated {b_adj}/30={b_adj/30:.3f}')
    print(f'rules-arm strict {strict}/30={strict/30:.3f}')
    # 逐题变化
    changed = [(r['id'], r['strict'], next(x for x in base['details'] if x['id'] == r['id'])['ok']) for r in out]
    print('flips:', [(i, 'wrong->right' if s and not b else 'right->wrong' if not s and b else '') for i, s, b in changed if s != b])
    json.dump({'strict': strict, 'details': out, 'elapsed_s': round(time.time()-t0,1)},
              open('/tmp/poc30b_results.json','w'), ensure_ascii=False, indent=1)
