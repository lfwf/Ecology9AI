"""Passive Chinese B09 structural catalog; no business query or active content."""
import json,hashlib
from catalog_reports import cell,table,csv_file

LABELS={'visible':'可见','not_visible':'当前账号未取得','available':'已取得定义','not_applicable':'不适用',
'empty_definition':'定义为空，未解释','unavailable_with_permission':'有定义权限但未取得正文',
'structure_candidate':'字段结构候选，语义待校准','object_not_visible':'对象未取得','schema_ambiguous':'同名多schema，未选择',
'column_not_visible_or_ambiguous':'列未取得或歧义','column_type_mismatch':'两端类型不同','view_definition_required':'须先取得视图定义',
'string_without_verified_format_or_timezone':'字符串，格式与时区待校准','native_sql_temporal_type':'SQL时间类型，时区待校准',
'numeric_or_other_unit_unverified':'数值/其他类型，单位待校准','sys_metadata':'系统元数据','local_source_reference':'指定本机源码参考'}
def label(v):return LABELS.get(v,v)
def yn(v):return '有结构证明' if v is True else '未取得结构证明' if v is False else '未知'
def dump(v):return json.dumps(v,ensure_ascii=False,indent=2)
def pre(v):return '<pre>'+cell(v if isinstance(v,str) else dump(v))+'</pre>'
def page(path,name,title,body):
    css='body{font:16px/1.7 system-ui;margin:28px;color:#1b2836}table{border-collapse:collapse;font-size:14px}th,td{border:1px solid #cbd4df;padding:7px;vertical-align:top;text-align:left;max-width:680px;overflow-wrap:anywhere}th{background:#edf2f7}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:12px}details{margin:16px 0}summary{font-weight:600;cursor:pointer}a{color:#155a91}p{max-width:1100px}'
    (path/name).write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+cell(title)+'</title><style>'+css+'</style>'+body+'</html>','utf-8')
def type_text(c):
    return str(c['data_type'])+' / 长度字节 '+str(c.get('max_length'))+' / 精度 '+str(c.get('precision'))+' / 小数 '+str(c.get('scale'))

def report_b09(path,raw,doc,diff):
    master='B09运行记录数据结构.html';s=doc['summary']
    body='<h1>B09 运行记录数据结构 · 待审核</h1>'
    body+='<p>采集区间：'+cell(raw['started_at'])+' 至 '+cell(raw['ended_at'])+'。仅系统元数据与指定本机代码参考；业务单据、待办、事件、视图结果和日志内容读取均为0。</p>'
    body+='<p>登记对象'+str(s['requested_object_count'])+'个；当前可见'+str(s['visible_object_count'])+'个，列'+str(s['column_count'])+'项，索引'+str(s['index_count'])+'组，外键'+str(s['foreign_key_count'])+'组，逻辑连接候选'+str(s['relationship_count'])+'项。</p>'
    body+='<ul>'+''.join('<li>'+cell(x)+'</li>' for x in doc['limitations'])+'</ul>'
    body+='<h2>对象目录</h2><p>点开对象查看字段、完整键组成、定义可见性及本机参考。ID或identity本身不证明唯一；没有结构证明不等于已发现重复。</p>'
    links=[];objectrows=[];fieldrows=[]
    for o in doc['objects']:
        address=[o['schema_name'],o['object_name']]
        filename='B09对象_'+hashlib.sha256(json.dumps(address,ensure_ascii=False).encode('utf-8')).hexdigest()[:20]+'.html'
        full=(o['schema_name']+'.' if o['schema_name'] else '')+o['object_name']
        links.append('<li><a href="'+cell(filename)+'">'+cell(full)+' · '+cell(o['purpose'])+'</a>（'+cell(label(o['visibility_state']))+'）</li>')
        keys='；'.join(','.join(k['key_columns']) for k in o['unique_keys'])
        objectrows.append([o['schema_name'],o['object_name'],o['purpose'],label(o['visibility_state']),o.get('can_select'),o.get('can_view_definition'),label(o['definition_state']),len(o['columns']),keys,o['grain_note']])
        detail='<p><a href="'+master+'">返回运行记录结构目录</a></p><h1>'+cell(full)+' · '+cell(o['purpose'])+'</h1><p>'+cell(o['grain_note'])+'</p>'
        detail+='<p>当前可见性：'+cell(label(o['visibility_state']))+'；SELECT权限原值：'+cell(o.get('can_select'))+'；VIEW DEFINITION原值：'+cell(o.get('can_view_definition'))+'；定义状态：'+cell(label(o['definition_state']))+'。未验证业务行粒度与线上加载版本。</p>'
        rows=[]
        for c in o['columns']:
            r=[o['schema_name'],o['object_name'],c['column_id'],c['column_name'],c['data_type'],c.get('max_length'),c.get('precision'),c.get('scale'),c.get('is_nullable'),c.get('is_identity'),c.get('is_computed')]
            rows.append(r[2:]);fieldrows.append(r)
        detail+='<h2>字段结构</h2>'+table(['序号','列名','类型','长度字节','精度','小数','可空原值','identity原值','计算列原值'],rows)
        detail+='<h2>索引完整组成</h2>'+table(['索引','键列','包含列','无过滤且启用的唯一性'],[[i['index_name'],','.join(i['key_columns']),','.join(i['included_columns']),yn(i['unfiltered_unique_proven'])] for i in o['indexes']])
        detail+='<details><summary>索引原始组件与标志</summary>'+pre(o['indexes'])+'</details>'
        detail+='<h2>外键组件</h2>'+pre([x for x in doc['foreign_keys'] if x['schema_name']==o['schema_name'] and x['object_name']==o['object_name']])
        detail+='<h2>扩展属性</h2>'+pre(o.get('extended_properties',[]))
        if o.get('type_desc')=='VIEW':
            detail+='<h2>视图定义</h2><p>'+cell(label(o['definition_state']))+'。未执行视图；过滤、汇总、去重与历史覆盖须另有定义证据。</p>'
            if o['definition'] is not None:detail+=pre(o['definition'])
        detail+='<h2>逻辑连接候选</h2>'+pre([r for r in doc['relationships'] if o['object_name'] in [r['source_object'],r['target_object']]])
        detail+='<h2>状态与引用列口径</h2>'+pre([x for x in doc['state_fields'] if x['schema_name']==o['schema_name'] and x['object_name']==o['object_name']])
        detail+='<h2>时间字段</h2>'+table(['字段','类型','存储分类','时区确认','单位确认'],[[x['column_name'],x['data_type'],label(x['storage_class']),x['timezone_verified'],x['unit_verified']] for x in doc['time_fields'] if x['schema_name']==o['schema_name'] and x['object_name']==o['object_name']])
        detail+='<h2>本机源码参考</h2><p>引用只说明本机代码上下文；不构成线上加载或完整状态字典证明。</p>'+pre(o['local_references'])
        page(path,filename,full,detail)
    body+='<ul>'+''.join(links)+'</ul>'
    objheaders=['schema','对象','用途','可见性','SELECT原值','VIEW DEFINITION原值','定义状态','字段数','有证明的完整唯一键','粒度说明']
    body+=table(objheaders,objectrows)
    relheaders=['源对象','源列','目标对象','目标列','结构检查','目标完整唯一键','完整可信外键','连接依据','使用条件','业务基数验证']
    relrows=[[r['source_object'],','.join(r['source_columns']),r['target_object'],','.join(r['target_columns']),label(r['state']),yn(r['parent_unique_key_proven']),yn(r['foreign_key_enforced']),r['basis'],r.get('context_guard'),r['business_cardinality_verified']] for r in doc['relationships']]
    body+='<h2>关联候选</h2><p>结构检查通过仍需要业务语义校准。字段类型相同不证明关联正确、历史完整或实际一对多；主明细聚合须先固定粒度。</p>'+table(relheaders,relrows)
    semanticrows=[]
    for x in doc['state_fields']:
        semanticrows.append([x['schema_name'],x['object_name'],x['column_name'],'状态/引用口径',x['data_type'],'完整编码字典尚未确认','；'.join(r['reference_key'] for r in x['local_references']),False,False])
    for x in doc['time_fields']:
        semanticrows.append([x['schema_name'],x['object_name'],x['column_name'],'时间口径',x['data_type'],label(x['storage_class']),'',x['timezone_verified'],x['unit_verified']])
    body+='<h2>状态与时间口径</h2>'+table(['schema','对象','列','类别','类型','当前结论','源码参考键','确认项1','确认项2'],semanticrows)
    body+='<h2>指定源码参考</h2>'
    for ref in doc['local_reference_files']:
        body+='<details><summary>'+cell(ref['reference_key'])+' · '+cell(ref.get('available'))+'</summary><p>'+cell(ref['path'])+'；SHA256：'+cell(ref.get('sha256'))+'</p>'+pre(ref.get('topics',[]))+pre(ref.get('snippets',[]))+'</details>'
    body+='<h2>来源覆盖</h2>'
    cover=[[n,label(v['role']),v['raw_records'],v['represented_records']] for n,v in sorted(doc['source_coverage'].items())]
    body+=table(['来源','类型','原记录数','表示记录数'],cover)
    body+='<h2>待核对</h2>'+pre(doc['issues'])
    body+='<details><summary>未关联元数据</summary>'+pre(doc['unassociated_metadata'])+'</details>'
    body+='<p>批次比较：'+cell(diff['status'])+'。明细见diff.json；当前成功批次与已审核批次分开保存。本轮没有代替用户确认状态编码、数据关系或分析口径。</p>'
    page(path,master,'B09运行记录数据结构',body)
    csv_file(path/'运行对象目录.csv',objheaders,objectrows)
    csv_file(path/'运行字段字典.csv',['schema','对象','序号','列名','类型','长度字节','精度','小数','可空原值','identity原值','计算列原值'],fieldrows)
    for source,filename in [('indexes','运行索引组件.csv'),('foreign_keys','运行外键组件.csv')]:
        rows=doc['metadata_catalogs'].get(source,[]);headers=sorted({key for row in rows for key in row}) or ['当前未取得组件']
        csv_file(path/filename,headers,[[r.get(h) for h in headers] for r in rows])
    csv_file(path/'运行关联候选.csv',relheaders,relrows)
    csv_file(path/'状态与时间口径.csv',['schema','对象','列','类别','类型','当前结论','源码参考键','时区或编码确认','单位确认'],semanticrows)
    csv_file(path/'运行结构来源覆盖.csv',['来源','类型','原记录数','表示记录数'],cover)
    csv_file(path/'运行未关联元数据.csv',['来源','来源记录下标','元数据'],[[x['source'],x['source_record_index'],dump(x['metadata'])] for x in doc['unassociated_metadata']])
