"""Bounded, passive Java/class evidence for OA action registrations.

This is a lexer and file inventory, not a Java interpreter or a control-flow
verifier. Stored instructions, SQL, URLs and class files are never executed.
"""
import hashlib,re,struct
from collections import deque,defaultdict
from pathlib import Path
from categories.b05 import safe as base_safe
from sql_refs import table_references,tokens as sql_tokens,identifier_at

VERSION='1.0.4'
CLASS=re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*')
SENSITIVE=r'[\w$.-]*(?:password|passwd|pwd|token|secret|authorization|cookie|api[_-]?key|private[_-]?key)[\w$.-]*'
def _masked(value):return '[REDACTED]'+''.join(x for x in value if x in '\r\n')
def _primitive_text(text):
    text=base_safe(str(text))
    # XML element values, attributes, setters, JSON keys, URLs/JDBC/header literals.
    text=re.sub(r'(?is)(<(?P<tag>(?:[\w.-]+:)?'+SENSITIVE+r')\b[^>]*>)(?P<value>.*?)(</(?P=tag)\s*>)',
                lambda m:m[1]+_masked(m['value'])+m[4],text)
    text=re.sub(r'(?is)(\b'+SENSITIVE+r'\s*=\s*)(["\'])(.*?)(\2)',
                lambda m:m[1]+m[2]+_masked(m[3])+m[4],text)
    text=re.sub(r'(?is)(["\']'+SENSITIVE+r'["\']\s*[:,]\s*)(["\'])(.*?)(\2)',
                lambda m:m[1]+m[2]+_masked(m[3])+m[4],text)
    text=re.sub(r'(?i)((?:[?&;]|\b)'+SENSITIVE+r'=)([^;&\s<>"\']+)',lambda m:m[1]+'[REDACTED]',text)
    text=re.sub(r'(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+',r'\1[REDACTED]',text)
    return text

def sanitize_text(text):
    text=_primitive_text(text)
    # Check decoded Java literal data too, so escaped JSON/XML cannot bypass
    # the primitive text patterns. A sensitive compound literal is masked whole.
    ts,_=java_tokens(text);spans=[]
    for t in ts:
        if t['kind']=='string' and _primitive_text(t['value'])!=t['value']:spans.append((t['start'],t['end']))
    # Mask explicit credential setter arguments before snippets are sliced.
    for j,t in enumerate(ts):
        if t['kind']!='id' or not re.fullmatch(r'(?i)(?:set|with)'+SENSITIVE,t['value']):continue
        if j+1>=len(ts) or ts[j+1]['kind']!='punct' or ts[j+1]['value']!='(':continue
        depth=1;k=j+2
        while k<len(ts) and depth:
            if ts[k]['kind']=='punct':
                depth+=int(ts[k]['value']=='(')-int(ts[k]['value']==')')
            k+=1
        if depth==0:spans.append((ts[j+1]['end'],ts[k-1]['start']))
    merged=[]
    for start,end in sorted(spans):
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    for start,end in reversed(merged):text=text[:start]+'"[REDACTED]"'+''.join(x for x in text[start:end] if x in '\r\n')+text[end:]
    return text

def java_tokens(text):
    out=[];warnings=[];i=0;line=1;n=len(text)
    while i<n:
        if text[i].isspace():line+=int(text[i]=='\n');i+=1;continue
        start=i;startline=line
        if text.startswith('//',i):
            stop=text.find('\n',i);i=n if stop<0 else stop;continue
        if text.startswith('/*',i):
            stop=text.find('*/',i+2)
            if stop<0:stop=n;warnings.append('unterminated_comment')
            else:stop+=2
            line+=text[i:stop].count('\n');i=stop;continue
        if text.startswith('"""',i):
            stop=text.find('"""',i+3)
            if stop<0:stop=n;warnings.append('unterminated_text_block');value=text[i+3:]
            else:value=text[i+3:stop];stop+=3
            line+=text[i:stop].count('\n');i=stop;kind='string'
        elif text[i] in ['"',"'"]:
            quote=text[i];i+=1;chars=[]
            while i<n:
                if text[i]==quote:i+=1;break
                if text[i]=='\\' and i+1<n:
                    chars.append({'n':'\n','r':'\r','t':'\t','"':'"',"'":"'","\\":"\\"}.get(text[i+1],'\\'+text[i+1]));i+=2
                else:chars.append(text[i]);line+=int(text[i]=='\n');i+=1
            else:warnings.append('unterminated_literal')
            value=''.join(chars);kind='string' if quote=='"' else 'char'
        else:
            match=re.match(r'[^\W\d][\w$]*|[$][\w$]+',text[i:],re.UNICODE)
            if match:value=match[0];i+=len(value);kind='id'
            else:value=text[i];i+=1;kind='punct'
        out.append(dict(kind=kind,value=value,start=start,end=i,line=startline))
    if re.search(r'\\u+[0-9a-fA-F]{4}',text):warnings.append('unicode_escapes_not_expanded')
    return out,sorted(set(warnings))

def sql_fragment(text,**where):
    parsed=table_references(text);ts,_=sql_tokens(text);targets=[]
    if ts:
        first=ts[0][1].upper();pos=1
        if first=='INSERT' and len(ts)>1 and ts[1][1].upper()=='INTO':pos=2
        if first=='MERGE' and len(ts)>1 and ts[1][1].upper()=='INTO':pos=2
        if first=='DELETE' and len(ts)>1 and ts[1][1].upper()=='FROM':pos=2
        if first in ['UPDATE','INSERT','MERGE','DELETE']:
            ref,_=identifier_at(ts,pos)
            if ref:targets.append(dict(ref,evidence_state='literal_write_target_candidate'))
    return dict(text=sanitize_text(text),write_target_candidates=targets,read_source_candidates=parsed['candidates'],
                target_state='literal_target_candidate' if targets else 'dynamic_or_unresolved',warnings=parsed['warnings'],
                executed=False,**where)

def java_evidence(text):
    ts,warnings=java_tokens(text);clean=sanitize_text(text);cleanlines=clean.splitlines()
    def snippet(line):
        return cleanlines[line-1][:1600] if 0<line<=len(cleanlines) else ''
    imports=[];package='';skip=set();i=0
    while i<len(ts):
        if ts[i]['kind']=='id' and ts[i]['value'] in ['package','import']:
            start=i;word=ts[i]['value'];i+=1;parts=[];valid=True
            while i<len(ts) and not (ts[i]['kind']=='punct' and ts[i]['value']==';'):
                if ts[i]['kind']!='id' and not (ts[i]['kind']=='punct' and ts[i]['value'] in ['.','*']):valid=False
                parts.append(ts[i]['value']);i+=1
            skip.update(range(start,min(i+1,len(ts))))
            name=''.join(x for x in parts if x!='static')
            base=name[:-2] if name.endswith('.*') and word=='import' else name
            if not valid or not CLASS.fullmatch(base):warnings.append('unparsed_package_or_import')
            elif word=='package':package=name
            else:imports.append(dict(name=name,static='static' in parts,line=ts[start]['line']))
        i+=1
    active=[(j,t) for j,t in enumerate(ts) if j not in skip]
    symbols={t['value'] for _,t in active if t['kind']=='id'}
    if len(symbols)>5000:raise ValueError('Source symbol cap exceeded')
    types=sorted(x for x in symbols if x and (x[0].isupper() or x[0]=='$'))
    qualified=set()
    for j,t in active:
        if t['kind']!='id':continue
        parts=[t['value']];k=j+1
        while k+1<len(ts) and k not in skip and ts[k]['kind']=='punct' and ts[k]['value']=='.' and ts[k+1]['kind']=='id':
            parts.append(ts[k+1]['value']);k+=2
            if len(parts)>1:qualified.add('.'.join(parts))
    returns=[];fields=[];calls=[];sql=[];controls=[]
    for j,t in active:
        value=t['value'];line=t['line']
        if t['kind']=='string' and re.match(r'(?is)^\s*(SELECT|WITH|UPDATE|INSERT|DELETE|MERGE)\b',value):
            sql.append(sql_fragment(value,line=line,evidence_state='java_literal_fragment'))
        if t['kind']!='id':continue
        if value=='return':
            end=j+1
            while end<len(ts) and not (ts[end]['kind']=='punct' and ts[end]['value']==';'):end+=1
            finish=ts[end]['start'] if end<len(ts) else len(text)
            returns.append(dict(line=line,expression=sanitize_text(text[t['end']:finish].strip())[:1800],snippet=snippet(line),evidence_state='return_expression_only'))
        if value in ['if','catch','throw','switch','synchronized']:
            controls.append(dict(line=line,keyword=value,snippet=snippet(line),evidence_state='lexical_control_reference'))
        if j+1<len(ts) and ts[j+1]['value']=='(' and value not in ['if','for','while','switch','catch','synchronized']:
            receiver=ts[j-2]['value'] if j>1 and ts[j-1]['kind']=='punct' and ts[j-1]['value']=='.' and ts[j-2]['kind']=='id' else None
            calls.append(dict(line=line,name=value,receiver=receiver,snippet=snippet(line),evidence_state='lexical_call_or_declaration'))
            if value in ['get','put','getString','getFieldValue','getParameter','set','addProperty'] and j+3<len(ts):
                arg=ts[j+2]
                if arg['kind']=='string' and ts[j+3]['value'] in [')',','] and re.fullmatch(r'[\w$.-]{1,100}',arg['value'],re.UNICODE):
                    fields.append(dict(line=line,accessor=value,receiver=receiver,field_literal=arg['value'],snippet=snippet(line),evidence_state='literal_key_not_verified_field_mapping'))
    if any(len(x)>5000 for x in [returns,fields,calls,sql,controls]):raise ValueError('Source signal cap exceeded')
    return dict(evidence_state='java_lexical_evidence',package=package,imports=imports,type_candidates=types,identifier_candidates=sorted(symbols),qualified_type_candidates=sorted(qualified),field_accesses=fields,returns=returns,
                sql_fragments=sql,calls=calls,control_fragments=controls,warnings=warnings,complete_control_flow=False,executed=False)

def class_evidence(data):
    result=dict(evidence_state='constant_pool_only',member_references=[],class_references=[],sql_fragments=[],warnings=[],complete_control_flow=False,executed=False)
    try:
        if len(data)<10 or data[:4]!=b'\xca\xfe\xba\xbe':raise ValueError('Not class format')
        minor,major,count=struct.unpack_from('>HHH',data,4);result['class_version']=[major,minor]
        cp=[None]*count;pos=10;i=1
        def need(n):
            if pos+n>len(data):raise ValueError('Truncated constant pool')
        while i<count:
            need(1);tag=data[pos];pos+=1
            if tag==1:
                need(2);length=struct.unpack_from('>H',data,pos)[0];pos+=2;need(length)
                cp[i]=(tag,data[pos:pos+length].decode('utf-8',errors='replace'));pos+=length
            elif tag in [3,4]:need(4);pos+=4
            elif tag in [5,6]:need(8);pos+=8;i+=1
            elif tag in [7,8,16,19,20]:need(2);cp[i]=(tag,struct.unpack_from('>H',data,pos)[0]);pos+=2
            elif tag in [9,10,11,12,17,18]:need(4);cp[i]=(tag,*struct.unpack_from('>HH',data,pos));pos+=4
            elif tag==15:need(3);pos+=3
            else:raise ValueError('Unknown constant type')
            i+=1
        def utf(index):return cp[index][1] if 0<index<len(cp) and cp[index] and cp[index][0]==1 else None
        classes=set()
        for item in cp:
            if not item:continue
            if item[0]==7:
                name=(utf(item[1]) or '').replace('/','.')
                if CLASS.fullmatch(name):classes.add(name)
            elif item[0] in [9,10,11]:
                a,b=cp[item[1]],cp[item[2]]
                if a and a[0]==7 and b and b[0]==12:result['member_references'].append(dict(owner=sanitize_text((utf(a[1]) or '').replace('/','.')),name=sanitize_text(utf(b[1]) or ''),descriptor=sanitize_text(utf(b[2]) or ''),kind={9:'field',10:'method',11:'interface_method'}[item[0]],evidence_state='constant_pool_reference_not_call_proof'))
            elif item[0]==1 and re.match(r'(?is)^\s*(SELECT|WITH|UPDATE|INSERT|DELETE|MERGE)\b',item[1]):
                result['sql_fragments'].append(sql_fragment(item[1],evidence_state='constant_pool_literal_not_execution'))
        result['class_references']=sorted(classes)
    except (ValueError,IndexError,struct.error):
        result.update(evidence_state='constant_pool_unavailable',warnings=['class_format_not_fully_read'])
    return result

def decode_source(data):
    if data.startswith((b'\xff\xfe',b'\xfe\xff')):return data.decode('utf-16'),'utf-16-bom'
    for encoding in ['utf-8-sig','gb18030']:
        try:return data.decode(encoding),encoding
        except UnicodeDecodeError:pass
    return data.decode('utf-8',errors='replace'),'utf-8-replacement'

def scan_sources(registrations,profile):
    limits=dict(max_files=600,max_depth=6,max_file_bytes=3000000,max_total_bytes=50000000)
    limits.update(profile.get('limits',{}))
    for k,lo,hi in [('max_files',1,1000),('max_depth',0,12),('max_file_bytes',1,5000000),('max_total_bytes',1,100000000)]:
        if not isinstance(limits.get(k),int) or not lo<=limits[k]<=hi:raise ValueError('Invalid source limit')
    roots=[]
    if not isinstance(profile.get('roots'),list) or not 1<=len(profile['roots'])<=12:raise ValueError('Invalid source roots')
    for root in profile['roots']:
        if root.get('kind') not in ['source','classes','both']:raise ValueError('Invalid source root kind')
        path=Path(root['path']).resolve()
        if path.parent==path:raise ValueError('Drive root is not a source scope')
        roots.append((path,root['kind']))
    prefixes=profile.get('compiled_dependency_prefixes',[])
    if not isinstance(prefixes,list) or any(not isinstance(x,str) or not x or '/' in x or '\\' in x for x in prefixes):raise ValueError('Invalid compiled dependency prefixes')
    lookup_cache={}
    def candidates(name,java_only=False):
        cache_key=(name,java_only)
        if cache_key in lookup_cache:return lookup_cache[cache_key]
        if len(lookup_cache)>=50000:
            frontier.append(dict(class_name=name,reason='name_lookup_cap'))
            return [],['name_lookup_cap']
        found=[];states=[]
        for root,kind in roots:
            suffixes=['.java'] if java_only else ['.java','.class']
            for suffix in suffixes:
                if suffix=='.java' and kind=='classes' or suffix=='.class' and kind=='source':continue
                part=Path(*name.split('.'))
                if suffix=='.java' and '$' in part.name:part=part.with_name(part.name.split('$',1)[0])
                path=(root/part).with_suffix(suffix)
                resolved=path.resolve()
                if not resolved.is_relative_to(root):states.append('path_outside_root');continue
                try:
                    if resolved.is_file():found.append((resolved,'source' if suffix=='.java' else 'compiled_copy'))
                except OSError:states.append('file_not_readable')
        answer=(sorted(set(found),key=lambda x:(str(x[0]),x[1])),states)
        lookup_cache[cache_key]=answer
        return answer
    files={};classfiles=defaultdict(list);processed=set();queue=deque();origins=[];edges=[];frontier=[];total=0
    for row in registrations:
        name=row.get('actionclass') or '';valid=bool(CLASS.fullmatch(name))
        origins.append(dict(registration_id=row.get('id'),class_name=name,lookup_state='pending' if valid else 'invalid_literal_class',file_keys=[],runtime_loaded_verified=False))
        if valid:queue.append((name,0))
    while queue:
        name,depth=queue.popleft()
        if name in processed:continue
        paths,states=candidates(name)
        if depth>limits['max_depth']:
            frontier.append(dict(class_name=name,reason='depth_cap'));continue
        processed.add(name)
        for path,kind in paths:
            key=hashlib.sha256(str(path).encode('utf-8')).hexdigest()
            if key in files:
                if key not in classfiles[name]:classfiles[name].append(key)
                continue
            if len(files)>=limits['max_files']:frontier.append(dict(class_name=name,path=str(path),reason='file_count_cap'));continue
            try:
                if path.stat().st_size>limits['max_file_bytes']:frontier.append(dict(class_name=name,path=str(path),reason='file_byte_cap'));continue
                with path.open('rb') as f:data=f.read(limits['max_file_bytes']+1)
                if len(data)>limits['max_file_bytes']:frontier.append(dict(class_name=name,path=str(path),reason='file_byte_cap'));continue
                if total+len(data)>limits['max_total_bytes']:frontier.append(dict(class_name=name,path=str(path),reason='total_byte_cap'));continue
                total+=len(data)
            except OSError:
                frontier.append(dict(class_name=name,path=str(path),reason='file_not_readable'));continue
            if kind=='source':
                text,encoding=decode_source(data);evidence=java_evidence(text)
            else:encoding=None;evidence=class_evidence(data)
            entry=dict(file_key=key,class_name=name,path=str(path),kind=kind,size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),encoding=encoding,evidence=evidence,runtime_loaded_verified=False)
            files[key]=entry;classfiles[name].append(key)
            targets=set()
            if kind=='source':
                symbols=set(evidence['identifier_candidates']);ids=symbols;pack=evidence['package']
                targets.update(evidence['qualified_type_candidates'])
                if evidence['warnings']:frontier.append(dict(class_name=name,path=str(path),reason='java_lexical_unsupported'))
                for im in evidence['imports']:
                    target=im['name']
                    if im['static']:
                        owner,member=target.rsplit('.',1)
                        if member=='*' or member in ids:targets.add(owner)
                    elif target.endswith('.*'):
                        targets.update(target[:-1]+x for x in symbols)
                    elif target.rsplit('.',1)[-1] in symbols:targets.add(target)
                if pack:targets.update(pack+'.'+x for x in symbols)
            else:
                if evidence['evidence_state']=='constant_pool_unavailable':frontier.append(dict(class_name=name,path=str(path),reason='class_constant_pool_unreadable'))
                targets.update(x for x in evidence['class_references'] if any(x.startswith(prefix) for prefix in prefixes))
            for target in sorted(targets):
                if target==name or not CLASS.fullmatch(target):continue
                available,_=candidates(target,java_only=True)
                if not available and kind=='compiled_copy' and any(target.startswith(x) for x in prefixes):available,_=candidates(target)
                if available:
                    edge=dict(source_file_key=key,source_class=name,target_class=target,relation='visible_lexical_symbol_file_candidate',runtime_verified=False)
                    if edge not in edges:edges.append(edge)
                    if target not in processed:queue.append((target,depth+1))
    for origin in origins:
        if origin['lookup_state']=='invalid_literal_class':continue
        name=origin['class_name'];origin['file_keys']=sorted(set(classfiles[name]))
        _,states=candidates(name)
        origin['lookup_state']='files_visible' if origin['file_keys'] else 'path_outside_root' if 'path_outside_root' in states else 'not_visible'
    frontier=[dict(x) for x in sorted({tuple(sorted(x.items())) for x in frontier})]
    # Evidence is deterministic across independent reads; no capture time inside rows.
    return dict(format_version=1,method_version=VERSION,registrations=origins,files=sorted(files.values(),key=lambda x:x['path']),
                edges=sorted(edges,key=lambda x:(x['source_file_key'],x['target_class'])),frontier=frontier,closed=not frontier,
                scope='registered_classes_and_visible_lexical_symbol_file_candidates',total_bytes=total,business_rows_read=0,executed=False,
                limitations=['本机可见文件及静态词法/常量池，不证明线上加载或执行。','词法符号匹配文件只是候选，不证明Java绑定或调用发生；未恢复完整控制流或反射依赖。','常量池字符串不是已执行SQL；敏感字面量遮蔽不计算动态表达式。'])


def capture_sources(input_path,profile_path,output_path):
    """Capture two independent passive reads into a new immutable local file."""
    import json
    from datetime import datetime,timezone
    from categories.b05 import sanitize_script
    inp=Path(input_path).resolve();pp=Path(profile_path).resolve();out=Path(output_path).resolve()
    if out.exists():raise FileExistsError('Evidence output exists')
    started=datetime.now(timezone.utc).isoformat()
    input_bytes=inp.read_bytes();profile_bytes=pp.read_bytes()
    raw=json.loads(input_bytes.decode('utf-8-sig'));profile=json.loads(profile_bytes.decode('utf-8-sig'))
    if not isinstance(raw,dict) or raw.get('business_rows_read')!=0:raise ValueError('Expected configuration-only input')
    registrations=raw.get('tables',{}).get('actionsetting')
    if not isinstance(registrations,list) or len(registrations)>2000 or any(not isinstance(x,dict) or not isinstance(x.get('actionclass'),(str,type(None))) for x in registrations):raise ValueError('Invalid action registration list')
    for root in profile.get('roots',[]):
        if out.is_relative_to(Path(root['path']).resolve()):raise ValueError('Evidence output must be outside source roots')
    support={'source_evidence.py':Path(__file__),'sql_refs.py':Path(sql_tokens.__code__.co_filename),
             'categories/b05.py':Path(base_safe.__code__.co_filename),'oa_workflow_analyzer/scripts.py':Path(sanitize_script.__code__.co_filename)}
    hashes={k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in support.items()}
    first=scan_sources(registrations,profile);second=scan_sources(registrations,profile)
    encoded=lambda d:json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    stable=encoded(first)==encoded(second)
    input_stable=input_bytes==inp.read_bytes() and profile_bytes==pp.read_bytes()
    support_stable=all(hashlib.sha256(v.read_bytes()).hexdigest()==hashes[k] for k,v in support.items())
    state='captured' if stable and input_stable and support_stable and first['closed'] else 'incomplete' if stable and input_stable and support_stable else 'changed_during_read'
    result=dict(format_version=1,category='B08_source_evidence',method_version=VERSION,status=state,
                started_at=started,ended_at=datetime.now(timezone.utc).isoformat(),
                input_sha256=hashlib.sha256(input_bytes).hexdigest(),profile_sha256=hashlib.sha256(profile_bytes).hexdigest(),
                implementation_hashes=hashes,two_reads_equal=stable,input_and_profile_stable=input_stable,implementation_stable=support_stable,
                evidence_sha256=hashlib.sha256(encoded(first)).hexdigest(),second_evidence_sha256=hashlib.sha256(encoded(second)).hexdigest(),
                evidence=first,business_rows_read=0,runtime_verified=False)
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    return result

def main():
    import argparse,json
    parser=argparse.ArgumentParser(description='Read local Java/class evidence only; never execute registered code.')
    parser.add_argument('--input',required=True,help='Configuration-only capture with tables.actionsetting')
    parser.add_argument('--profile',required=True,help='Local source roots and finite limits')
    parser.add_argument('--output',required=True,help='New evidence file outside source roots')
    args=parser.parse_args()
    try:
        result=capture_sources(args.input,args.profile,args.output)
        e=result['evidence']
        print(json.dumps(dict(status=result['status'],output=str(Path(args.output).resolve()),registrations=len(e['registrations']),files=len(e['files']),
                              closed=e['closed'],frontier_count=len(e['frontier']),two_reads_equal=result['two_reads_equal'],business_rows_read=0),ensure_ascii=False))
        return 0 if result['status']=='captured' else 1
    except (OSError,ValueError,KeyError,TypeError):
        print(json.dumps(dict(status='failed',stage='source_evidence_capture',business_rows_read=0,details_suppressed=True)))
        return 1

if __name__=='__main__':
    raise SystemExit(main())
