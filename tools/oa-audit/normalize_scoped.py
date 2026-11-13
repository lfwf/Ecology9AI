"""Normalize an isolated live configuration capture without changing foundation batches."""
import json,sys,hashlib
from pathlib import Path
HOME=Path(__file__).resolve().parents[1]/'oa-foundation'
sys.path.insert(0,str(HOME))
from categories import b02,b03,b04,b05
def normalize(capture,foundation,output):
 raw=json.loads(Path(capture).read_text('utf-8'));base=Path(foundation)/'oa-local'
 st=json.loads((base/'B01/state.json').read_text('utf-8'));old=json.loads((base/'B01/batches'/st['latest_success']/'normalized.json').read_text('utf-8'))
 anchor=raw['anchor'][0];w=next(x for x in old['workflows'] if x['id']==raw['workflow_id'])
 if w['form_id']!=anchor['formid'] or w['name']!=anchor['workflowname']:raise ValueError('Workflow meaning changed')
 seed={'workflows':[w]};docs={}
 for cat,module in [('B02',b02),('B03',b03),('B04',b04),('B05',b05)]:
  docs[cat]=module.normalize(raw['categories'][cat]['tables'],seed);seed[cat]=docs[cat]
 result={'capture_sha256':hashlib.sha256(Path(capture).read_bytes()).hexdigest(),'captured_at':raw['ended_at'],'workflow_id':raw['workflow_id'],'categories':docs}
 with Path(output).open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
 return result
if __name__=='__main__':
 try:normalize(*sys.argv[1:]);print('{"status":"normalized_local_only"}')
 except (ValueError,KeyError,TypeError,OSError):print('{"status":"failed","stage":"local_normalization"}');raise SystemExit(1)
