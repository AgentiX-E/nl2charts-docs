import duckdb, json
def ast(sql):
    return json.loads(duckdb.sql("select json_serialize_sql(?)",params=[sql]).fetchone()[0])
def find(n,pred):
    out=[]
    if isinstance(n,dict):
        if pred(n): out.append(n)
        for v in n.values(): out+=find(v,pred)
    elif isinstance(n,list):
        for v in n: out+=find(v,pred)
    return out
d=ast("SELECT a FROM t UNION SELECT a FROM u")
so=find(d,lambda x:x.get('type')=='SET_OPERATION_NODE')[0]
tf=find(ast("SELECT * FROM read_parquet('x.parquet')"),lambda x:x.get('type')=='TABLE_FUNCTION')
print(duckdb.__version__,
      '| children_present',('children' in so),'children_len',(len(so['children']) if 'children' in so else None),
      '| children_eq_left_right', ('children' in so and so['children']==[so.get('left'),so.get('right')]),
      '| table_function_keys', sorted(tf[0].keys()) if tf else None)
