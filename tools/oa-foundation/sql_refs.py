"""Conservative SQL identifier evidence; never executes SQL or resolves a connection."""
import json,re,sys
from pathlib import Path
_ID=re.compile(r'[^\W\d][\w$#@]*|[@#][\w$#@]+',re.UNICODE)
def tokens(text):
    out=[];warnings=[];i=0
    while i<len(text):
        if text[i].isspace():i+=1;continue
        if text.startswith('--',i):
            end=text.find('\n',i);i=len(text) if end<0 else end;continue
        if text.startswith('/*',i):
            depth=1;i+=2
            while i<len(text) and depth:
                if text.startswith('/*',i):depth+=1;i+=2
                elif text.startswith('*/',i):depth-=1;i+=2
                else:i+=1
            if depth:warnings.append('unterminated_comment')
            continue
        if text[i]=="'":
            i+=1
            while i<len(text):
                if text.startswith("''",i):i+=2
                elif text[i]=="'":i+=1;break
                else:i+=1
            out.append(('literal',''));continue
        if text[i] in '["':
            begin=text[i];end=']' if begin=='[' else '"';i+=1;value=[];closed=False
            while i<len(text):
                if text.startswith(end+end,i):value.append(end);i+=2
                elif text[i]==end:i+=1;closed=True;break
                else:value.append(text[i]);i+=1
            if not closed:warnings.append('unterminated_identifier')
            out.append(('id',''.join(value)));continue
        m=_ID.match(text,i)
        if m:
            value=m[0];out.append(('variable' if value.startswith(('@','#')) else 'id',value));i=m.end();continue
        out.append(('punct',text[i]));i+=1
    return out,warnings
def identifier_at(ts,i):
    parts=[]
    if i>=len(ts) or ts[i][0]!='id':return None,i
    parts.append(ts[i][1]);i+=1
    while i<len(ts) and ts[i][1]=='.':
        i+=1
        if i<len(ts) and ts[i][1]=='.':parts.append(None);continue
        if i<len(ts) and ts[i][0]=='id':parts.append(ts[i][1]);i+=1
        else:return None,i
    if len(parts)>4 or parts[-1] is None or any(p is not None and (not p or len(p)>128 or any(ord(c)<32 for c in p)) for p in parts):return None,i
    return dict(server=parts[-4] if len(parts)==4 else None,database=parts[-3] if len(parts)>=3 else None,
                schema=parts[-2] if len(parts)>=2 else None,object_name=parts[-1],parts=parts),i
def split_identifier(text):
    raw=str(text or '').strip()
    ts,_=tokens(raw);ref,end=identifier_at(ts,0)
    if ref is not None and end==len(ts):return ref
    # Configuration stores a literal object name, not an executable SQL token.
    # Digit-leading names require quoting in SQL, but remain valid metadata values.
    if re.fullmatch(r'[\w$]{1,128}',raw,re.UNICODE):
        return dict(server=None,database=None,schema=None,object_name=raw,parts=[raw])
    return None
def table_references(text):
    ts,warnings=tokens(str(text or ''));aliases=set()
    # CTE names are derived relations, not independently queryable base objects.
    for i,t in enumerate(ts):
        if t[1].upper() not in ('WITH',','):continue
        ref,end=identifier_at(ts,i+1)
        if ref and len(ref['parts'])==1:
            if end<len(ts) and ts[end][1]=='(':
                depth=1;end+=1
                while end<len(ts) and depth:
                    depth+=int(ts[end][1]=='(')-int(ts[end][1]==')');end+=1
            if end+1<len(ts) and ts[end][1].upper()=='AS' and ts[end+1][1]=='(':aliases.add(ref['object_name'].casefold())
    result=[];seen=set();depth=0;from_depths=set()
    def add(i):
        if i>=len(ts):return
        if ts[i][0]=='variable':warnings.append('dynamic_or_temporary_source');return
        ref,end=identifier_at(ts,i)
        if not ref:
            if end>i:warnings.append('qualified_identifier_unresolved')
            return
        if end<len(ts) and ts[end][1]=='(':
            warnings.append('table_function_or_external_source');return
        if ref['object_name'].upper() in ('OPENQUERY','OPENROWSET','OPENDATASOURCE'):
            warnings.append('external_source_not_followed');return
        if len(ref['parts'])==1 and ref['object_name'].casefold() in aliases:return
        key=tuple(ref['parts'])
        if key not in seen:seen.add(key);result.append(dict(ref,evidence_state='lexical_candidate_not_verified_relation'))
    for i,(kind,value) in enumerate(ts):
        upper=value.upper()
        if value=='(':
            depth+=1;continue
        if value==')':
            from_depths.discard(depth);depth=max(0,depth-1);continue
        if upper in ('SELECT','WHERE','GROUP','HAVING','ORDER','UNION','EXCEPT','INTERSECT','OPTION'):
            from_depths.discard(depth)
        if upper=='FROM':
            from_depths.add(depth);add(i+1)
        elif upper in ('JOIN','APPLY'):add(i+1)
        elif value==',' and depth in from_depths:add(i+1)
        if upper in ('EXEC','EXECUTE'):warnings.append('dynamic_execution_text_not_followed')
    return dict(candidates=result,warnings=sorted(set(warnings)),executed=False,complete_sql_semantics=False)
def main():
    source=Path(sys.argv[1]);target=Path(sys.argv[2]);database=sys.argv[3]
    data=json.loads(source.read_text('utf-8-sig'));references=[];local_names=set();problems=[]
    for item in data:
        if item.get('kind')=='identifier':
            declared=split_identifier(item.get('text',''));parsed=dict(candidates=[declared] if declared else [],warnings=[] if declared else ['identifier_not_resolved'])
        else:parsed=table_references(item.get('text',''))
        for ref in parsed['candidates']:
            ref.update(source=item['source'],source_id=item.get('source_id'),field=item.get('field'),
                       local_database_candidate=not item.get('unverified_datasource',False) and not ref['server'] and (ref['database'] is None or ref['database'].casefold()==database.casefold()))
            if ref['local_database_candidate']:local_names.add(ref['object_name'])
            references.append(ref)
        if parsed['warnings']:problems.append(dict(source=item['source'],source_id=item.get('source_id'),warnings=parsed['warnings']))
    target.write_text(json.dumps(dict(references=references,local_object_names=sorted(local_names),warnings=problems),ensure_ascii=False),'utf-8')
if __name__=='__main__':main()
