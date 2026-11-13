"""Static automation definitions and inert script evidence, never an execution engine."""
import hashlib,json,re,sys
from collections import Counter,defaultdict
from .b04 import PLATFORM_FIELDS
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'oa-workflow-analyzer'/'src'))
from oa_workflow_analyzer.scripts import decode_layout_text,analyze_script,sanitize_script
from oa_workflow_analyzer.normalize import _layout
CATEGORY='B05'
NORMALIZATION_VERSION='1.0.0'
def val(row,key):
    return next((v for k,v in (row or {}).items() if k.casefold()==key.casefold()),None)
def integer(value):
    s=str(value).strip()
    return int(s) if re.fullmatch(r'-?\d+',s) else None
def safe(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if re.fullmatch(r'(?i)password|passwd|pwd|token|access[_-]?token|refresh[_-]?token|secret|client[_-]?secret|api[_-]?key|authorization|cookie|private[_-]?key',k) else safe(v)) for k,v in value.items()}
    if isinstance(value,list):return [safe(v) for v in value]
    if isinstance(value,str):
        value=sanitize_script(value)
        value=re.sub(r'(?i)(https?://)[^/@\s\'"<>]+@',r'\1[REDACTED]@',value)
        return re.sub(r'(?i)([?&#](?:token|access[_-]?token|refresh[_-]?token|api[_-]?key|secret|client[_-]?secret|password|pwd|authorization)=)[^&#\s\'"<>]+',r'\1[REDACTED]',value)
    return value
def normalize(tables,seed):
    issues=[];flows=[];covered=defaultdict(set)
    positions={name:{id(row):i for i,row in enumerate(rows)} for name,rows in tables.items()}
    def cover(name,row):covered[name].add(positions[name][id(row)])
    def issue(kind,**refs):issues.append(dict(kind=kind,**refs))
    b03={f['id']:f for f in seed['B03']['workflows']}
    expected={(f['id'],n['id']) for f in b03.values() for n in f['nodes']}
    if {(r['workflowid'],r['nodeid']) for r in tables['workflow_flownode']}!=expected:raise ValueError('Static nodes changed; refresh B03')
    field_index=defaultdict(list)
    for field in seed['B02']['fields']:field_index[(field['form_source'],field['form_id'],field['field_id'])].append(field)
    def ref(value,workflow,where):
        text=str(value or '').strip().strip("'\"")
        match=re.fullmatch(r'(?:field)?(-?\d+)(?:_\d+)?',text)
        if not match:return None
        fid=int(match[1])
        if fid in PLATFORM_FIELDS:
            name,technical_name=PLATFORM_FIELDS[fid]
            return dict(namespace='platform',field_id=fid,name=name,technical_name_reference=technical_name,physical_table=None,column_name=None,semantics_basis='B04_local_source_reference')
        candidates=field_index[(workflow['form_source'],workflow['form_id'],fid)]
        if len(candidates)!=1:
            issue('automation_field_unresolved',workflow_id=workflow['id'],source=where,field_id=fid);return None
        f=candidates[0]
        return {k:f.get(k) for k in ['form_source','form_id','field_id','name','column_name','physical_table']}
    def refs(text,workflow,where):
        tokens=re.findall(r'\[(?:main|detail_\d+)\.(-?\d+)\]|\bfield(-?\d+)(?:_\d+)?',str(text or ''))
        ids=list(dict.fromkeys(a or b for a,b in tokens))
        return [dict(field_id=int(fid),field_reference=ref(fid,workflow,where)) for fid in ids]
    def context_for(row,workflow,source):
        if val(row,'formid') is None or val(row,'isbill') is None:return workflow
        context=dict(workflow,form_id=val(row,'formid'),form_source={0:'workflow_formbase',1:'workflow_bill'}.get(integer(val(row,'isbill'))))
        if context['form_id']!=workflow['form_id'] or context['form_source']!=workflow['form_source']:issue('automation_form_context_conflict',workflow_id=workflow['id'],source=source,form_id=context['form_id'])
        return context
    def form_matches(row,workflow):
        isbill=val(row,'isbill')
        return val(row,'formid')==workflow['form_id'] and str(isbill)==str(workflow['isbill_raw'])
    def rows_for(name,workflow,form=False,node=False):
        nodes={n['id'] for n in b03.get(workflow['id'],{}).get('nodes',[])}
        result=[]
        for row in tables.get(name,[]):
            wid=val(row,'workflowid')
            if wid is None:wid=val(row,'flowid')
            match=wid==workflow['id'] or (form and wid in [None,0,-1] and form_matches(row,workflow))
            if not match:continue
            nid=val(row,'nodeid')
            if node and nid not in [None,0,-1] and nid not in nodes:continue
            result.append(row);cover(name,row)
        return result
    entries={r['id'] for r in tables.get('workflow_datainput_entry',[])}
    mains={r['id']:r for r in tables.get('workflow_datainput_main',[])}
    input_tables={r['id']:r for r in tables.get('workflow_datainput_table',[])}
    if len(mains)!=len(tables.get('workflow_datainput_main',[])) or len(input_tables)!=len(tables.get('workflow_datainput_table',[])):raise ValueError('Duplicate input definition id')
    if any(val(r,'entryid') not in entries for r in mains.values()):raise ValueError('Unassociated input main')
    if any(val(r,'datainputid') not in mains for r in input_tables.values()):raise ValueError('Unassociated input table')
    if any(val(r,'datainputid') not in mains for r in tables.get('workflow_datainput_field',[])):raise ValueError('Unassociated input mapping')
    if any(val(r,'requestid') not in [None,0] for r in tables.get('workflow_nodeOverTime',[])):raise ValueError('Runtime timeout record forbidden')
    rule_bases={r['id']:r for r in tables.get('rule_base',[])}
    timer_bases={r['id']:r for r in tables.get('workflow_nodeOverTime',[])}
    if len(rule_bases)!=len(tables.get('rule_base',[])) or len(timer_bases)!=len(tables.get('workflow_nodeOverTime',[])):raise ValueError('Duplicate static condition/timeout id')
    condition_catalog=[]
    child_sources=['rule_expressionbase','rule_expressions','rule_maplist','rule_mapitem']
    condition_ids=set(rule_bases)
    for name in child_sources:
        condition_ids.update(integer(val(r,'ruleid')) for r in tables.get(name,[]) if integer(val(r,'ruleid')) is not None)
    condition_ids.update(integer(val(r,'ruleid')) for r in timer_bases.values() if integer(val(r,'ruleid')) not in [None,0])
    for rid in sorted(condition_ids):
        rb=rule_bases.get(rid)
        if rb:cover('rule_base',rb)
        context=dict(id=None,form_id=val(rb,'formid'),form_source={0:'workflow_formbase',1:'workflow_bill'}.get(integer(val(rb,'isbill')))) if rb else None
        children={}
        for name in child_sources:
            children[name]=[r for r in tables.get(name,[]) if integer(val(r,'ruleid'))==rid]
            for row in children[name]:cover(name,row)
        terms=[dict(configuration=safe(r),field_reference=ref(val(r,'datafield'),context,'timeout_condition') if context else None) for r in children['rule_expressionbase']]
        condition_catalog.append(dict(id=rid,definition_state='present' if rb else 'missing',configuration=safe(rb),terms=terms,
            expression_tree=safe(children['rule_expressions']),mapping_candidates=safe(children['rule_maplist']),parameter_mapping_candidates=safe(children['rule_mapitem']),
            mapping_semantics='raw source/link namespaces retained; no inferred priority or boolean combination',evaluated=False))
    conditions_by_id={r['id']:r for r in condition_catalog}
    for workflow in seed['workflows']:
        wid=workflow['id'];flow=dict(id=wid,name=workflow['name'],layouts=[],formulas=[],linkages=[],data_inputs=[],field_attributes=[],actions=[],numbering=[],withdrawal=[],function_permissions=[],overtime=[],link_reminders=[])
        for row in rows_for('workflow_nodehtmllayout',workflow,form=True,node=True):
            context=context_for(row,workflow,'workflow_nodehtmllayout')
            record=dict(ref='layout:'+str(row['id']),values={k.casefold():'' if v is None else str(v) for k,v in row.items()})
            design_text=str(val(row,'datajson') or '')
            if design_text.lstrip().startswith(('{','[')):
                design=dict(text=design_text,status='plain',input_sha256=hashlib.sha256(design_text.encode('utf-8')).hexdigest())
            else:design=decode_layout_text(design_text)
            record['values']['datajson']=design.get('text','')
            parsed_issues=[];parsed=_layout(record,parsed_issues)
            for gap in parsed_issues:issue(gap['code'],workflow_id=wid,layout_id=row['id'])
            active={1:True,0:False}.get(val(row,'isactive'));scripts=[];seen={}
            for channel in ['scriptstr','scripts','initScripts']:
                original=val(row,channel)
                if not original or not str(original).strip():continue
                decoded=decode_layout_text(str(original));text=decoded.get('text','');key=text.replace('\r\n','\n').replace('\r','\n').strip() if decoded['status']!='unsupported' else str(original)
                if key in seen:seen[key]['channels'].append(channel);continue
                clean=safe(text);analysis=analyze_script(clean)
                writes=[dict(evidence=x,field_reference=ref(x.get('target'),context,'layout_script')) for x in analysis['field_writes']]
                attrs=[dict(evidence=x,field_reference=ref(x.get('target'),context,'layout_script_attribute')) for x in analysis['attribute_changes']]
                item=dict(channels=[channel],decoding={k:v for k,v in decoded.items() if k!='text'},text=clean,analysis=analysis,field_writes=writes,attribute_changes=attrs,executed=False)
                scripts.append(item);seen[key]=item
                if decoded['status']=='unsupported':issue('layout_script_decode_unsupported',workflow_id=wid,layout_id=row['id'],channel=channel)
            if active is None:issue('layout_activity_unknown',workflow_id=wid,layout_id=row['id'],raw=val(row,'isactive'))
            config={k:v for k,v in row.items() if k.casefold() not in ['datajson','scripts','scriptstr','initscripts','pluginjson','stylestr']}
            placements=[dict(configuration=safe(p),field_reference=ref(p['field_id'],context,'layout_placement')) for p in parsed['placements']]
            flow['layouts'].append(dict(id=row['id'],node_id=val(row,'nodeid'),name=val(row,'layoutname'),active_reference=active,configuration=safe(config),
                parse_status=parsed.get('parse_status'),placements_known=parsed.get('placements_known'),placements=placements,scripts=scripts,
                design_input_sha256=design['input_sha256'],design_decoding_state=design['status'],runtime_verified=False))
        for row in rows_for('workflow_formula_htmllayout',workflow,form=True,node=True):
            context=context_for(row,workflow,'workflow_formula_htmllayout')
            flow['formulas'].append(dict(configuration=safe(row),field_references=refs(val(row,'formula'),context,'formula')+refs(val(row,'formulatxt'),context,'formula_text'),
                destination_field_reference=ref(val(row,'destfield'),context,'formula_destination'),triggers_raw=val(row,'triggers'),evaluated=False))
        for row in rows_for('workflow_viewattrlinkage',workflow,node=True):
            targets=re.split(r'[,;，\s]+',str(val(row,'changefieldids') or ''))
            flow['linkages'].append(dict(configuration=safe(row),trigger_field_reference=ref(val(row,'selectfieldid'),workflow,'linkage_trigger'),
                target_field_references=[dict(raw=x,field_reference=ref(x,workflow,'linkage_target')) for x in targets if x],stored_viewattr_raw=val(row,'viewattr'),runtime_verified=False))
        for row in rows_for('workflow_datainput_entry',workflow):
            item=dict(id=row['id'],configuration=safe(row),trigger_field_reference=ref(val(row,'triggerfieldname'),workflow,'input_trigger'),
                enabled_reference={0:True,1:False}.get(val(row,'enable')),enabled_basis='local_E9_reference_0_enabled_1_disabled; isdel separate',queries=[])
            for main in mains.values():
                if val(main,'entryid')!=row['id']:continue
                cover('workflow_datainput_main',main)
                children=[r for r in input_tables.values() if val(r,'datainputid')==main['id']]
                for child in children:cover('workflow_datainput_table',child)
                child_ids={r['id'] for r in children};mappings=[]
                for mapping in tables.get('workflow_datainput_field',[]):
                    if val(mapping,'datainputid')!=main['id']:continue
                    cover('workflow_datainput_field',mapping)
                    tableid=val(mapping,'tableid')
                    if tableid not in child_ids and tableid not in [None,0,-1]:issue('input_mapping_table_unresolved',workflow_id=wid,mapping_id=mapping['id'],table_id=tableid)
                    mappings.append(dict(configuration=safe(mapping),source_table_reference=safe(input_tables.get(tableid)) if tableid in child_ids else None,target_field_reference=ref(val(mapping,'pagefieldname'),workflow,'input_target'),mapping_type_raw=val(mapping,'type')))
                item['queries'].append(dict(id=main['id'],configuration=safe(main),tables=safe(children),mappings=mappings,executed=False))
            flow['data_inputs'].append(item)
        for row in rows_for('workflow_nodefieldattr',workflow,form=True,node=True):
            flow['field_attributes'].append(dict(configuration=safe(row),field_reference=ref(val(row,'fieldid'),workflow,'field_attribute'),evaluated=False))
        for row in rows_for('workflow_addinoperate',workflow):
            nid=val(row,'objid') if val(row,'isnode')==1 else None
            nodes={n['id'] for n in b03.get(wid,{}).get('nodes',[])}
            if nid is not None and nid not in nodes:issue('action_node_scope_conflict',workflow_id=wid,action_id=val(row,'id'),node_id_raw=nid)
            code=val(row,'isnode');binding_kind={1:'node',0:'link'}.get(code,'unknown')
            candidates=b03.get(wid,{}).get('nodes',[]) if code==1 else b03.get(wid,{}).get('routes',[]) if code==0 else []
            target=next((r for r in candidates if r['id']==val(row,'objid')),None)
            binding_ref={k:target.get(k) for k in ['id','name','from_node','to_node'] if k in target} if target else None
            if code==0 and binding_ref is None:issue('action_link_reference_unresolved',workflow_id=wid,action_id=val(row,'id'),link_id_raw=val(row,'objid'))
            flow['actions'].append(dict(configuration=safe(row),node_id=nid,binding_kind=binding_kind,binding_reference=binding_ref,node_scope_state='matched_or_non_node' if nid is None or nid in nodes else 'conflict_pending',field_reference=ref(val(row,'fieldid'),workflow,'action_target'),
                operand_fields=[dict(raw=val(row,key),field_reference=ref(val(row,key),workflow,'action_operand')) for key in ['fieldop1id','fieldop2id'] if val(row,key) not in [None,0,-1]],
                action_type_raw=val(row,'type'),isdisable_raw=val(row,'isdisable'),ispreadd_raw=val(row,'ispreadd'),executed=False))
        for name in ['workflow_code','workflow_coderegulate']:
            for row in rows_for(name,workflow,form=True):
                flow['numbering'].append(dict(source=name,configuration=safe(row),field_reference=ref(val(row,'codefieldid'),context_for(row,workflow,name),'numbering') if name=='workflow_code' else None,counter_values_read=False))
        for source,target in [('workflow_requestwithdraw','withdrawal'),('workflow_function_manage','function_permissions'),('workflow_nodeOverTime','overtime'),('workflow_nodeOverTime_Detail','overtime'),('workflow_nodelinkOverTime','link_reminders')]:
            for row in rows_for(source,workflow,node=source in ['workflow_nodeOverTime','workflow_nodeOverTime_Detail']):
                item=dict(source=source,configuration=safe(row),executed=False)
                if source=='workflow_nodeOverTime':
                    item['date_field_reference']=ref(val(row,'datefield'),workflow,'timeout_date');item['time_field_reference']=ref(val(row,'timefield'),workflow,'timeout_time')
                if source=='workflow_nodeOverTime':
                    rid=integer(val(row,'ruleid'));item['rule_id_raw']=val(row,'ruleid')
                    item['independent_condition']=conditions_by_id.get(rid)
                    if rid not in [None,0] and (item['independent_condition'] is None or item['independent_condition']['definition_state']=='missing'):issue('timeout_condition_missing',workflow_id=wid,timeout_id=val(row,'id'),rule_id=rid)
                    if val(row,'ruleid') not in [None,''] and rid is None:issue('timeout_condition_reference_unsupported',workflow_id=wid,timeout_id=val(row,'id'))
                elif source=='workflow_nodeOverTime_Detail':
                    parent=timer_bases.get(integer(val(row,'overtimeid')))
                    matched=parent and val(parent,'workflowid')==wid and val(parent,'nodeid')==val(row,'nodeid')
                    item['parent_timeout_reference']=dict(id=parent['id'],node_id=val(parent,'nodeid')) if matched else None
                    if not matched:issue('timeout_reminder_parent_unresolved',workflow_id=wid,reminder_id=val(row,'id'),parent_id_raw=val(row,'overtimeid'))
                flow[target].append(item)
        flows.append(flow)
    global_sources={'workflow_flownode','workflow_nodebase','workflow_nodelink','workflow_formula','schedulesetting'}
    unassociated=[];coverage={}
    for source,rows in tables.items():
        if source in global_sources:covered[source]=set(range(len(rows)))
        for i,row in enumerate(rows):
            if i not in covered[source]:
                unassociated.append(dict(source=source,source_record_index=i,configuration=safe(row),association_state='unassociated_pending'))
                issue('automation_configuration_unassociated',source=source,source_record_index=i)
        coverage[source]=dict(raw_records=len(rows),associated_records=len(covered[source]),unassociated_records=len(rows)-len(covered[source]))
    kinds=['layouts','formulas','linkages','data_inputs','field_attributes','actions','numbering','withdrawal','function_permissions','overtime','link_reminders']
    return dict(category=CATEGORY,normalization_version=NORMALIZATION_VERSION,semantic_state='partial_pending_confirmation',workflows=flows,
        timer_condition_definitions=condition_catalog,formula_catalog=safe(tables.get('workflow_formula',[])),schedule_candidates=[dict(configuration=safe(r),association_state='workflow_class_candidate_only_not_bound_to_individual_workflow',executed=False) for r in tables.get('schedulesetting',[])],
        issues=issues,unassociated_configurations=unassociated,source_coverage=coverage,business_rows_read=0,summary=dict(workflow_count=len(flows),counts={k:sum(len(f[k]) for f in flows) for k in kinds},
            script_count=sum(len(l['scripts']) for f in flows for l in f['layouts']),issue_counts=dict(Counter(i['kind'] for i in issues))),
        limitations=['脚本词法扫描与布局静态解析不执行源代码；静态调用不证明线上成功。','活动、停用与未知布局分别保留；设备、视图、版本组合仍待校准。','编号只读规则，不读currentCode、流水计数；调度只读定义，不读运行状态和任务参数。','报表与带入SQL仅作字符串，不执行；字段关系按带来源的表单ID关联。','本机E9解码/启用参考与线上部署可能不同，全部待审核。'])
