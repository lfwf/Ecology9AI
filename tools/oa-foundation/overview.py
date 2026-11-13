"""Reusable offline nine-category index and captured-evidence audit. No SQL access."""
import argparse,hashlib,json,os
from pathlib import Path
from urllib.parse import quote
import foundation as f
import catalog_store as store
from catalog_reports import cell,table

def load_audited_batch(base,batch_id,method):
    path,manifest=f.load_batch(base,batch_id)
    required={'raw.json','normalized.json','diff.json',method.get('report_file','流程目录.html')}
    actual={p.name for p in path.iterdir() if p.name!='manifest.json'}
    if not required.issubset(manifest['files']) or actual!=set(manifest['files']):raise ValueError('Batch manifest file coverage mismatch')
    if any(not p.is_file() or p.is_symlink() for p in path.iterdir()):raise ValueError('Unexpected batch filesystem entry')
    return path,manifest

def coverage_state(category,doc,tables):
    coverage=doc.get('source_coverage')
    if coverage is None:
        if category=='B01':return 'raw_source_checks_verified'
        if category in ['B02','B03','B04']:return 'not_recorded_in_legacy_format'
        raise ValueError('Normalized source coverage absent: '+category)
    if set(coverage)!=set(tables):raise ValueError('Normalized coverage source set mismatch')
    partitioned=False
    for name,rows in tables.items():
        v=coverage[name]
        count=v.get('represented_records')
        if count is None:
            count=v.get('associated_records',-1)+v.get('unassociated_records',-1)
            partitioned=True
        if v.get('raw_records')!=len(rows) or count!=len(rows):raise ValueError('Normalized source coverage incomplete: '+category)
    return 'partition_counts_verified' if partitioned else 'represented_counts_verified'

def inspect_environment(root,environment):
    base=f.category_dir(root,environment).parent
    entries=[];source_ids=set()
    for number in range(1,10):
        category='B%02d'%number
        method=f.read_json(f.HOME/'registry'/f'{category}.json')
        if not (f.HOME/method['reader']).is_file():raise ValueError('Registered reader missing: '+category)
        state=f.status(root,environment) if category=='B01' else store.status(root,environment,category)
        entry=dict(category=category,name=method['name'],state='not_captured',latest_reviewed=state['latest_reviewed'],batch_id=state['latest_success'])
        if not state['latest_success']:
            entries.append(entry);continue
        batch,manifest=load_audited_batch(base/category,state['latest_success'],method)
        raw=f.read_json(batch/'raw.json');doc=f.read_json(batch/'normalized.json');diff=f.read_json(batch/'diff.json')
        if raw.get('category')!=category or manifest.get('category')!=category:raise ValueError('Batch category mismatch')
        if manifest.get('reading_state')!='success' or manifest.get('business_rows_read')!=0 or raw.get('business_rows_read',0)!=0:raise ValueError('Scope evidence invalid')
        expected=set(method['tables']) if category=='B01' else set(method['sources'])|set(method.get('metadata_sources',[]))
        if set(raw['tables'])!=expected or set(raw['checks'])!=expected:raise ValueError('Source coverage incomplete: '+category)
        for name,rows in raw['tables'].items():
            c=raw['checks'][name]
            if not c.get('complete') or c.get('row_count')!=len(rows) or not c.get('hash_first') or c['hash_first']!=c.get('hash_second'):raise ValueError('Incomplete two-pass evidence: '+category)
        normalized_coverage=coverage_state(category,doc,raw['tables'])
        dependencies=[]
        for dep,record in manifest.get('dependencies',{}).items():
            depbatch,_=load_audited_batch(base/dep,record['batch_id'],f.read_json(f.HOME/'registry'/f'{dep}.json'))
            if hashlib.sha256((depbatch/'raw.json').read_bytes()).hexdigest()!=record['raw_sha256']:raise ValueError('Dependency hash mismatch: '+category)
            dependencies.append(dict(category=dep,batch_id=record['batch_id']))
        if set(method.get('dependencies',[]))!={x['category'] for x in dependencies}:raise ValueError('Declared dependency missing: '+category)
        report=method.get('report_file','流程目录.html')
        if report not in manifest['files'] or not (batch/report).is_file():raise ValueError('Registered report missing')
        if state['latest_reviewed']:
            # Verify a real accepted selection using existing batch review machinery.
            selected=f.selected_batch(root,environment) if category=='B01' else store.selected_batch(root,environment,category)
            if selected.name!=state['latest_reviewed']:raise ValueError('Review selection mismatch')
        source_ids.add(f.digest(raw['source_identity']))
        entry.update(state='accepted' if state['latest_reviewed']==batch.name else 'pending',
            report=str(batch/report),started_at=raw['started_at'],ended_at=raw['ended_at'],method_version=raw['method_version'],
            semantic_state=doc['semantic_state'],sources={n:len(rows) for n,rows in raw['tables'].items()},
            checked_file_count=len(manifest['files']),dependencies=dependencies,diff_state=diff['status'],
            issue_counts=doc.get('summary',{}).get('issue_counts') or dict(__import__('collections').Counter(i['kind'] for i in doc.get('issues',[]))),
            summary=doc.get('summary',{}),business_rows_read=0,normalized_coverage_state=normalized_coverage)
        entries.append(entry)
    return dict(environment=environment,checked_at=f.stamp(),offline_only=True,categories=entries,
        all_categories_present=all(e['state']!='not_captured' for e in entries),single_captured_source=len(source_ids)==1,
        explanation='只核对已保存批次、双遍、覆盖、依赖与文件哈希，不表示数据库刚刷新，也不代替用户确认语义。')

def write_overview(root,environment):
    result=inspect_environment(root,environment);base=f.category_dir(root,environment).parent;base.mkdir(parents=True,exist_ok=True)
    rows=[];details=''
    for e in result['categories']:
        status={'not_captured':'未采集','pending':'待审核','accepted':'本批已接受审核'}[e['state']]
        rows.append([e['category'],e['name'],status,e['batch_id'],e.get('ended_at'),len(e.get('sources',{})),e.get('checked_file_count',0)])
        if 'report' not in e:continue
        link=quote(Path(os.path.relpath(e['report'],base)).as_posix(),safe='/')
        details+='<h2>'+cell(e['category']+' '+e['name'])+'</h2><p><a href="'+cell(link)+'">打开本批目录</a> · '+cell(status)+'</p>'
        details+='<p>原始采集区间：'+cell(e['started_at'])+' 至 '+cell(e['ended_at'])+'。'+cell(e['semantic_state'])+'；差异状态：'+cell(e['diff_state'])+'。</p>'
        details+=table(['来源','记录数'],sorted(e['sources'].items()))
        coverage_labels={'raw_source_checks_verified':'原始来源检查已核验','not_recorded_in_legacy_format':'本批旧格式未登记统一逐源标准化计数；已核验原始来源、双遍、依赖与哈希，不能据此声称标准化逐行覆盖已证明','partition_counts_verified':'已关联与未关联分区计数平衡','represented_counts_verified':'逐源表示计数平衡'}
        details+='<p>覆盖证据：'+cell(coverage_labels[e['normalized_coverage_state']])+'。</p>'
        if e['issue_counts']:details+='<details><summary>待核对事项分类</summary><pre>'+cell(json.dumps(e['issue_counts'],ensure_ascii=False,indent=2))+'</pre></details>'
    body='<h1>OA基础数据总目录</h1><p>这是供校准的配置与结构目录。成功采集和接受审核分别记录；各类有独立采集时间，当前页面不会连接数据库。</p>'
    body+='<p>离线核对时间：'+cell(result['checked_at'])+'。九类均有成功批次：'+cell(result['all_categories_present'])+'；保存来源一致：'+cell(result['single_captured_source'])+'。</p>'
    body+=table(['类别','内容','审核状态','成功批次','原采集结束','来源数','已核验文件数'],rows)+details
    body+='<h2>更新与边界</h2><p>先按类别复用run.py refresh，再运行overview.py重建本页。上游改变时按依赖顺序更新，缺口留待校准。B05-L01旧流程模板检查仍需单独执行，主刷新尚未自动包含。</p>'
    body+='<p>V_JDSX定义、完整状态码、节点轮次与历史覆盖等以各类目录为准。这里没有读取具体业务单据，也没有建立MCP、数据库智能体入口、自动调度或逐字段机器校准规则库。</p>'
    text='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OA基础数据总目录</title><style>body{font:16px/1.7 system-ui;margin:28px;color:#18222b}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ccd3da;padding:7px;vertical-align:top;text-align:left}th{background:#edf2f6}.scroll{overflow:auto}pre{white-space:pre-wrap}h2{margin-top:36px}a{color:#155a91}</style>'+body+'</html>'
    out=base/'基础数据总目录.html'
    tmp=base/('.overview-'+__import__('uuid').uuid4().hex+'.html');tmp.write_text(text,'utf-8');tmp.replace(out)
    audit=base/'基础数据总审计.json';tmp=base/('.overview-'+__import__('uuid').uuid4().hex+'.json');f.write_json(tmp,result);tmp.replace(audit)
    return out

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='仅离线核对九类现有批次并重建中文总目录，不连接数据库')
    parser.add_argument('--data-root',type=Path,default=f.HOME/'.local');parser.add_argument('--environment',default='oa-local')
    args=parser.parse_args()
    if hasattr(__import__('sys').stdout,'reconfigure'):__import__('sys').stdout.reconfigure(encoding='utf-8')
    try:
        out=write_overview(args.data_root,args.environment)
        print(json.dumps(dict(status='success',report=str(out),audit=str(out.with_name('基础数据总审计.json')),database_access=False),ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,TypeError):
        print(json.dumps(dict(status='failed',action='Check saved batch integrity, declared source/dependency evidence and registered methods; no database access'),ensure_ascii=False))
        raise SystemExit(1)
