"""B09 narrowly scoped local source references. Never read log contents."""
import hashlib,json
from pathlib import Path
from datetime import datetime,timezone
from interface_sources import sanitize
from source_evidence import sanitize_text,decode_source
VERSION='1.0.0'
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
def collect_reference_files(profile):
    roots=[Path(x).resolve() for x in profile.get('roots',[])]
    if not 1<=len(roots)<=12 or any(p.parent==p for p in roots):raise ValueError('Invalid reference roots')
    refs=profile.get('references',[])
    if not isinstance(refs,list) or len(refs)>20:raise ValueError('Reference count cap exceeded')
    rows=[];seen=set();total=0
    for ref in refs:
        key=ref.get('key');p=Path(ref['path']).resolve();markers=ref.get('markers',[])
        if not isinstance(key,str) or not key or key in seen:raise ValueError('Reference key invalid or duplicated')
        seen.add(key)
        if p.suffix.lower() not in ['.java','.jsp'] or not any(p.is_relative_to(root) for root in roots):raise ValueError('Only explicitly scoped Java/JSP source references allowed')
        if not isinstance(markers,list) or len(markers)>40 or any(not isinstance(x,str) or not 1<=len(x)<=128 for x in markers):raise ValueError('Invalid source reference markers')
        row=dict(reference_key=key,path=str(p),available=False,sha256=None,snippets=[],topics=sanitize(ref.get('topics',[])),evidence_state='local_reference_only_not_loaded',runtime_verified=False)
        try:
            if p.stat().st_size>2000000:raise ValueError('Reference file cap exceeded')
            with p.open('rb') as stream:data=stream.read(2000001)
            if len(data)>2000000:raise ValueError('Reference file cap exceeded')
            total+=len(data)
            if total>10000000:raise ValueError('Reference total byte cap exceeded')
            text,encoding=decode_source(data);clean=sanitize_text(text);lines=clean.splitlines();selected=set()
            if encoding=='utf-8-replacement':raise ValueError('Source encoding unverified')
            for i,line in enumerate(lines):
                if any(marker.casefold() in line.casefold() for marker in markers):
                    selected.update(range(max(0,i-1),min(len(lines),i+2)))
            if len(selected)>300:raise ValueError('Reference line selection cap exceeded')
            row.update(available=True,sha256=hashlib.sha256(data).hexdigest(),size_bytes=len(data),encoding=encoding,
                       snippets=[dict(line=i+1,text=lines[i][:2000]) for i in sorted(selected)],source_line_count=len(lines))
        except FileNotFoundError:row['availability_state']='not_visible'
        except PermissionError:row['availability_state']='not_readable'
        rows.append(row)
    return rows
def capture_references(profile_path,output_path):
    pp=Path(profile_path).resolve();out=Path(output_path).resolve()
    if out.exists():raise FileExistsError('Reference output exists')
    before=pp.read_bytes();profile=json.loads(before.decode('utf-8-sig'))
    for root in profile.get('roots',[]):
        if out.is_relative_to(Path(root).resolve()):raise ValueError('Reference output must be outside source roots')
    from source_evidence import sanitize_text
    support={'runtime_references.py':Path(__file__),'interface_sources.py':Path(sanitize.__code__.co_filename),'source_evidence.py':Path(sanitize_text.__code__.co_filename)}
    hashes={k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in support.items()};started=datetime.now(timezone.utc).isoformat()
    first=collect_reference_files(profile);second=collect_reference_files(profile)
    stable=first==second and pp.read_bytes()==before and all(hashlib.sha256(v.read_bytes()).hexdigest()==hashes[k] for k,v in support.items())
    result=dict(format_version=1,category='B09_reference_sources',method_version=VERSION,status='captured' if stable else 'changed_during_read',
                started_at=started,ended_at=datetime.now(timezone.utc).isoformat(),profile_sha256=hashlib.sha256(before).hexdigest(),
                implementation_hashes=hashes,two_reads_equal=first==second,profile_and_code_stable=stable,
                expected_reference_keys=[r['key'] for r in profile.get('references',[])],files=first,files_sha256=digest(first),second_files_sha256=digest(second),business_rows_read=0)
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    return result
def verify_reference_capture(raw):
    c=raw.get('reference_evidence',{});files=raw.get('tables',{}).get('local_reference_files',[])
    if c.get('category')!='B09_reference_sources' or c.get('method_version')!=VERSION or c.get('status')!='captured' or c.get('two_reads_equal') is not True or c.get('profile_and_code_stable') is not True:raise ValueError('Reference capture incomplete')
    if not c.get('profile_sha256') or not c.get('implementation_hashes'):raise ValueError('Reference method evidence missing')
    if c.get('expected_reference_keys')!=[f.get('reference_key') for f in files]:raise ValueError('Reference keys mismatch')
    if c.get('files_sha256')!=digest(files) or c.get('second_files_sha256')!=digest(files):raise ValueError('Reference files mismatch')
    check=raw.get('checks',{}).get('local_reference_files',{})
    if check.get('hash_first')!=digest(files) or check.get('hash_second')!=digest(files):raise ValueError('Reference row hashes mismatch')
    if any(f.get('runtime_verified') is not False for f in files):raise ValueError('Unexpected runtime reference claim')
