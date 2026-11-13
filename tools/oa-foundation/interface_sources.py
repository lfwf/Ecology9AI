"""B08 source capture origins and passive configuration sanitization."""
import hashlib,json
from categories.b05 import val,integer
from source_evidence import sanitize_text,VERSION
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
def sanitize(value):
    if isinstance(value,dict):
        return {k:('[REDACTED_NOT_COLLECTED]' if k.casefold() in ['interfacepk','attrvalue','password','passwd','pwd','token','secret','authorization','cookie','api_key','client_secret','private_key'] else sanitize(v)) for k,v in value.items()}
    if isinstance(value,list):return [sanitize(v) for v in value]
    if isinstance(value,str):return sanitize_text(value)
    return value
def registration_rows(tables):
    rows=[]
    for row in tables.get('actionsetting',[]):
        rows.append(dict(id='actionsetting:'+str(val(row,'id')),actionclass=val(row,'actionclass') or ''))
    for row in tables.get('mode_pageexpanddetail',[]):
        if integer(val(row,'interfacetype'))!=3:continue
        for column in ['interfacevalue','javafileAddress']:
            if val(row,column):
                rows.append(dict(id='mode_pageexpanddetail:'+str(val(row,'id'))+':'+column,actionclass=str(val(row,column)).strip()))
    for source,column in [('wsformactionset','custominterface'),('CubeInterfaceConfig','encryptionPath')]:
        for row in tables.get(source,[]):
            if val(row,column):rows.append(dict(id=source+':'+str(val(row,'id'))+':'+column,actionclass=str(val(row,column)).strip()))
    return rows
def verify_source_capture(raw):
    c=raw.get('source_evidence',{});g=c.get('graph',{});files=raw.get('tables',{}).get('local_source_files',[])
    if c.get('category')!='B08_source_evidence' or c.get('format_version')!=1 or c.get('method_version')!=VERSION or c.get('status')!='captured' or c.get('two_reads_equal') is not True or c.get('input_and_profile_stable') is not True or c.get('implementation_stable') is not True or g.get('closed') is not True or g.get('frontier'):raise ValueError('Incomplete source evidence')
    if not c.get('profile_sha256') or not c.get('implementation_hashes'):raise ValueError('Missing source capture method evidence')
    expected=registration_rows(raw['tables'])
    if digest(expected)!=c.get('registration_rows_sha256'):raise ValueError('Source registration capture scope mismatch')
    if [(x['id'],x['actionclass']) for x in expected]!=[(x['registration_id'],x['class_name']) for x in g.get('registrations',[])]:raise ValueError('Source evidence registration mismatch')
    full=dict(g,files=files)
    if digest(full)!=c.get('evidence_sha256') or c.get('evidence_sha256')!=c.get('second_evidence_sha256'):raise ValueError('Source evidence hash mismatch')
    check=raw.get('checks',{}).get('local_source_files',{})
    if check.get('hash_first')!=digest(files) or check.get('hash_second')!=digest(files):raise ValueError('Source files hash mismatch')
    keys={x.get('file_key') for x in files}
    for row in files:
        if row.get('runtime_loaded_verified') is not False or row.get('evidence',{}).get('executed') is not False:raise ValueError('Unexpected runtime claim')
    for root in g.get('registrations',[]):
        if set(root.get('file_keys',[]))-keys:raise ValueError('Source file reference missing')
    return g
