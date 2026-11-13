"""Prepare a fixed registered configuration specification, restricted to one workflow."""
import json,re,hashlib,argparse
from pathlib import Path
HOME=Path(__file__).resolve().parents[1]/'oa-foundation'
def scoped_sql(name,sql,dependent):
 if name=='schedulesetting':
  sql=re.sub(r"c\.classpath\s+LIKE\s+'%workflow%'","c.classpath=@jobclass",sql,flags=re.I)
 elif name=='workflow_formula':return sql
 else:
  sql=re.sub(r'FROM dbo\.workflow_base b WHERE', 'FROM dbo.workflow_base b WHERE b.id=@workflow AND',sql,flags=re.I)
  sql=re.sub(r'FROM dbo\.workflow_base WHERE', 'FROM dbo.workflow_base WHERE id=@workflow AND',sql,flags=re.I)
  sql=re.sub(r'FROM dbo\.workflow_base(?=\))','FROM dbo.workflow_base WHERE id=@workflow',sql,flags=re.I)
 if '@workflow' not in sql and '@jobclass' not in sql and not(dependent and '{scope_ids}' in sql):raise ValueError('Unbounded registered configuration source')
 return sql
def prepare(workflow,output):
 if type(workflow) is not int or workflow<=0:raise ValueError('Invalid workflow')
 result={'workflow_id':workflow,'categories':{},'registry_sha256':{}}
 for cat in ['B02','B03','B04','B05']:
  p=HOME/'registry'/f'{cat}.json';raw=p.read_bytes();m=json.loads(raw)
  result['registry_sha256'][cat]=hashlib.sha256(raw).hexdigest()
  for name,s in m['sources'].items():s['sql']=scoped_sql(name,s['sql'],'reference_scope' in s or 'partition_by' in s)
  result['categories'][cat]=m
 p=Path(output)
 with p.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
 return len([s for m in result['categories'].values() for s in m['sources']])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--workflow',type=int,required=True);p.add_argument('--output',required=True);a=p.parse_args()
 try:prepare(a.workflow,a.output);print('{"status":"prepared"}')
 except (OSError,ValueError,KeyError):print('{"status":"failed","stage":"registered_scope"}');raise SystemExit(1)
