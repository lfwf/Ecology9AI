"""Batch persistence for registered configuration categories B02..B09."""
import hashlib,importlib,json,uuid
from collections import Counter,defaultdict
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import foundation as f

def method(category):
    if category not in ['B02','B03','B04','B05','B06','B07','B08','B09']:raise ValueError('Unknown category')
    return f.read_json(f.HOME/'registry'/f'{category}.json')

def category_dir(root,environment,category):
    method(category)
    return f.category_dir(root,environment).parent/category

def status(root,environment,category):
    p=category_dir(root,environment,category)/'state.json'
    return f.read_json(p) if p.exists() else dict(latest_success=None,latest_reviewed=None)

@contextmanager
def exclusive(base):
    lock=base/'.publish.lock';handle=lock.open('x')
    try:yield
    finally:handle.close();lock.unlink()

def validate(raw,m):
    if raw.get('format_version')!=1 or raw.get('business_rows_read')!=0 or raw.get('scope')!=m['scope']:raise ValueError('Invalid configuration capture scope')
    if not raw.get('schema') or not raw.get('source_identity'):raise ValueError('Missing source/schema evidence')
    if f.capture_time(raw['ended_at'])<f.capture_time(raw['started_at']):raise ValueError('Invalid capture interval')
    if m.get('requires_reference_graph') and (raw.get('reference_graph',{}).get('closed') is not True or not raw.get('reference_graph',{}).get('iterations')):raise ValueError('Incomplete reference graph scope')
    if m.get('requires_source_evidence'):
        from interface_sources import verify_source_capture
        verify_source_capture(raw)
    if m.get('requires_runtime_references'):
        from runtime_references import verify_reference_capture
        verify_reference_capture(raw)
    required=set(m['sources'])|set(m.get('metadata_sources',[]))
    if set(raw.get('tables',{}))!=required or set(raw.get('checks',{}))!=required:raise ValueError('Missing or unregistered sources')
    for name,rows in raw['tables'].items():
        check=raw['checks'][name]
        cap=m.get('metadata_limits',{}).get(name,m['sources'].get(name,{}).get('row_cap',m['limits'].get('max_physical_columns',50000)))
        if not isinstance(rows,list) or len(rows)>cap or not check.get('complete') or check.get('row_count')!=len(rows):raise ValueError('Incomplete source: '+name)
        if not check.get('hash_first') or check['hash_first']!=check.get('hash_second'):raise ValueError('Two-pass mismatch: '+name)
        if name in m['sources'] and sum(p['row_count'] for p in check['pages'])!=len(rows):raise ValueError('Pagination coverage mismatch: '+name)

def diff_rows(before,after,keys):
    def key(row):return f.encoded([row.get(k) for k in keys]).decode('utf-8')
    a=defaultdict(list);b=defaultdict(list)
    for row in before:a[key(row)].append(row)
    for row in after:b[key(row)].append(row)
    if any(len(rows)>1 for rows in list(a.values())+list(b.values())):
        ac=Counter(f.digest(r) for r in before);bc=Counter(f.digest(r) for r in after)
        return dict(status='ambiguous_keys_multiset',added=list((bc-ac).elements()),source_missing=list((ac-bc).elements()),changed=[])
    return dict(status='compared',added=sorted(b.keys()-a.keys()),source_missing=sorted(a.keys()-b.keys()),
                changed=[dict(key=k,fields=sorted(x for x in a[k][0].keys()|b[k][0].keys() if a[k][0].get(x)!=b[k][0].get(x)),
                              before_sha256=f.digest(a[k][0]),after_sha256=f.digest(b[k][0]))
                         for k in sorted(a.keys()&b.keys()) if a[k][0]!=b[k][0]])

def publish(root,environment,raw,seed,dependencies):
    category=raw['category'];m=method(category);validate(raw,m)
    if set(m.get('dependencies',[]))-set(dependencies):raise ValueError('Missing declared dependency')
    if m.get('requires_source_evidence'):seed=dict(seed,_source_graph=raw['source_evidence']['graph'])
    normalizer=importlib.import_module('categories.'+category.lower())
    doc=normalizer.normalize(raw['tables'],seed)
    base=category_dir(root,environment,category);base.mkdir(parents=True,exist_ok=True)
    compatibility=dict(source=f.digest(raw['source_identity']),scope=m['scope'],method=raw['method_version'],
        schema=f.digest(raw['schema']),reader=raw.get('implementation_hashes'),
        normalization=doc['normalization_version'],
        normalizer_code=hashlib.sha256(Path(normalizer.__file__).read_bytes()).hexdigest(),
        dependency_scope=f.digest([(w['id'],w['form_id'],w['isbill_raw']) for w in seed['workflows']]),
        dependent_models={k:f.digest(v) for k,v in seed.items() if k in ['B01','B02','B03','B04','B05','B06','B07','B08','B09']})
    if m.get('requires_source_evidence'):compatibility.update(source_profile=raw['source_evidence']['profile_sha256'],source_method=raw['source_evidence']['method_version'])
    if m.get('requires_runtime_references'):compatibility.update(reference_profile=raw['reference_evidence']['profile_sha256'],reference_method=raw['reference_evidence']['method_version'])
    if m.get('normalizer_support_files'):
        support={}
        for relative in m['normalizer_support_files']:
            source=(f.HOME/relative).resolve()
            if not source.is_relative_to(f.HOME.parent.resolve()) or not source.is_file():raise ValueError('Invalid normalizer support source')
            support[relative]=hashlib.sha256(source.read_bytes()).hexdigest()
        compatibility['normalizer_support_code']=support
    with exclusive(base):
        state=status(root,environment,category);diff=dict(status='baseline')
        if state['latest_success']:
            previous,manifest=f.load_batch(base,state['latest_success']);old=f.read_json(previous/'raw.json')
            if f.capture_time(raw['ended_at'])<f.capture_time(old['ended_at']):raise ValueError('Late older capture')
            if manifest['compatibility']!=compatibility:diff=dict(status='not_comparable',previous_batch=previous.name)
            else:
                diff=dict(status='compared',previous_batch=previous.name,sources={})
                for name,rows in raw['tables'].items():
                    keys=m.get('source_keys',{}).get(name,['id'])
                    diff['sources'][name]=diff_rows(old['tables'][name],rows,keys)
        batch_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:12]
        pending=base/('.pending-'+batch_id);pending.mkdir()
        f.write_json(pending/'raw.json',raw);f.write_json(pending/'normalized.json',doc);f.write_json(pending/'diff.json',diff)
        from catalog_reports import report
        report(pending,raw,doc,diff)
        if m.get('report_file') and (Path(m['report_file']).name!=m['report_file'] or not (pending/m['report_file']).is_file()):raise ValueError('Registered report missing')
        manifest=dict(batch_id=batch_id,environment=environment,category=category,created_at=f.stamp(),
            reading_state='success',semantic_state=doc['semantic_state'],review_state_at_capture='pending',
            business_rows_read=0,dependencies=dependencies,compatibility=compatibility,
            files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(pending.iterdir())})
        f.write_json(pending/'manifest.json',manifest)
        (base/'batches').mkdir(exist_ok=True);target=base/'batches'/batch_id;pending.rename(target)
        state['latest_success']=batch_id;f.replace_state(base,state)
        return target

def selected_batch(root,environment,category,unreviewed=False):
    state=status(root,environment,category);batch_id=state['latest_success' if unreviewed else 'latest_reviewed']
    if not batch_id:raise ValueError('No accepted batch; use explicit unreviewed inspection')
    base=category_dir(root,environment,category);path,manifest=f.load_batch(base,batch_id)
    if not unreviewed and state['latest_success']:
        _,latest=f.load_batch(base,state['latest_success'])
        if latest['compatibility']['source']!=manifest['compatibility']['source']:raise ValueError('Source changed')
    return path

def review(root,environment,category,batch_id,reviewer,decision,note,semantic_state):
    if decision not in ['accepted','needs_revision'] or semantic_state not in ['partial','confirmed'] or not reviewer.strip() or not note.strip():raise ValueError('Invalid review')
    base=category_dir(root,environment,category);_,manifest=f.load_batch(base,batch_id)
    with exclusive(base):
        folder=base/'reviews';folder.mkdir(exist_ok=True)
        f.write_json(folder/(uuid.uuid4().hex+'.json'),dict(batch_id=batch_id,reviewed_at=f.stamp(),reviewer=reviewer,
            decision=decision,note=note,semantic_state=semantic_state,normalization_version=manifest['compatibility']['normalization']))
        state=status(root,environment,category)
        if decision=='accepted':state['latest_reviewed']=batch_id
        elif state['latest_reviewed']==batch_id:state['latest_reviewed']=None
        f.replace_state(base,state)
