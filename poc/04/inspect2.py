import duckdb, json
def ast(sql):
    raw=duckdb.sql("select json_serialize_sql(?)",params=[sql]).fetchone()[0]
    return json.loads(raw)
def find(n,pred,path=''):
    out=[]
    if isinstance(n,dict):
        if pred(n): out.append((path,n))
        for k,v in n.items(): out+=find(v,pred,f'{path}/{k}')
    elif isinstance(n,list):
        for v in n: out+=find(v,pred,f'{path}[]')
    return out
R={}
# catalog.schema qualified table
for sql in ["SELECT * FROM cat.sch.t","SELECT * FROM sch.t"]:
    try:
        b=find(ast(sql),lambda x:x.get('type')=='BASE_TABLE')
        R[sql]={'keys':sorted(b[0][1].keys()),'vals':{k:b[0][1][k] for k in ('catalog_name','schema_name','table_name')}}
    except Exception as e: R[sql]={'error':str(e)[:100]}
# user-defined type name
for sql in ["SELECT CAST(a AS my_type) FROM t","SELECT CAST(a AS ENUM('x','y')) FROM t"]:
    try:
        d=ast(sql)
        ti=find(d,lambda x:isinstance(x.get('type_info'),dict))
        R[sql]={'type_info_keys':[sorted(v['type_info'].keys()) for _,v in ti][:3],'type_info':[v['type_info'] for _,v in ti][:2]}
    except Exception as e: R[sql]={'error':str(e)[:100]}
# nested union: is the only change children?
d=ast("SELECT a FROM t UNION SELECT a FROM u UNION SELECT a FROM v")
so=find(d,lambda x:x.get('type')=='SET_OPERATION_NODE')
R['nested_union']={'setop_nodes':len(so),'has_children':[('children' in n[1]) for n in so]}
print(json.dumps({'version':duckdb.__version__,**R},ensure_ascii=False,indent=1))
json.dump({'version':duckdb.__version__,**R},open(f'inspect2-{duckdb.__version__}.json','w'),ensure_ascii=False,indent=1)
