"""B08 static interface definitions and field handoffs, never runtime results."""
import re
from collections import defaultdict,Counter
from .b05 import val,integer
from interface_sources import sanitize
from sql_refs import table_references
def normalize(tables,seed):
    issues=[];used=defaultdict(set);groups={};workflows={w['id']:w for w in seed['workflows']}
    def issue(kind,**refs):issues.append(dict(kind=kind,**refs))
    def items(source):return list(enumerate(tables.get(source,[])))
    def mark(source,i):used[source].add(i)
    def children(source,key,parent):
        pair=(source,key)
        if pair not in groups:
            groups[pair]=defaultdict(list)
            for i,row in items(source):groups[pair][val(row,key)].append((i,row))
        return groups[pair].get(parent,[])
    def index(source):
        d={}
        for i,row in items(source):
            rid=val(row,'id')
            if rid in d:raise ValueError('Duplicate interface definition: '+source)
            d[rid]=row
        return d
    models=index('modeinfo');formdefs={};fieldidx=defaultdict(list)
    for f in seed['B06']['dictionary']['fields']:fieldidx[(f['form_source'],f['form_id'],f['field_id'])].append(f)
    def context(formid,isbill):return dict(form_id=integer(formid),form_source={0:'workflow_formbase',1:'workflow_bill'}.get(integer(isbill)))
    def wfcontext(wid):
        w=workflows.get(integer(wid));return dict(form_id=w['form_id'],form_source=w['form_source']) if w else dict(form_id=None,form_source=None)
    def modecontext(mid):
        m=models.get(integer(mid));return context(val(m,'formid'),1) if m else dict(form_id=None,form_source='workflow_bill')
    def fieldref(fid,ctx,where):
        fid=integer(fid)
        if fid is None:return None
        if fid==0:return dict(field_id=0,namespace='not_selected',semantics='原值0，未绑定字段')
        if fid<0:return dict(field_id=fid,namespace='interface_internal_unverified',semantics='本接口内置编号原值，未借用其他模块字典')
        matches=fieldidx[(ctx['form_source'],ctx['form_id'],fid)]
        if len(matches)!=1:issue('interface_field_unresolved',source=where,form_source=ctx['form_source'],form_id=ctx['form_id'],field_id=fid);return None
        return {k:matches[0].get(k) for k in ['form_source','form_id','field_id','name','column_name','physical_table']}
    b3={w['id']:w for w in seed['B03']['workflows']}
    def trigger(row,source):
        wid=integer(val(row,'workflowid'));nid=integer(val(row,'nodeid'));lid=integer(val(row,'nodelinkid'));flow=b3.get(wid,{})
        if nid and nid>0 and not any(n['id']==nid for n in flow.get('nodes',[])):issue('action_node_unresolved',source=source,id=val(row,'id'),workflow_id=wid,node_id=nid)
        if lid and lid>0 and not any(l['id']==lid for l in flow.get('routes',[])):issue('action_link_unresolved',source=source,id=val(row,'id'),workflow_id=wid,link_id=lid)
        return dict(workflow_id=wid,node_id=nid,link_id=lid,phase_raw=val(row,'ispreoperator'),order_raw=val(row,'actionorder'),enabled_raw=val(row,'isused'),drawback_raw=val(row,'drawbackflag'),runtime_verified=False)
    sourcegraph=seed.get('_source_graph',{});code={x['registration_id']:x for x in sourcegraph.get('registrations',[])}
    java=[]
    for i,row in items('actionsetting'):
        rid=val(row,'id');key='actionsetting:'+str(rid);mark('actionsetting',i);params=[]
        for j,r in children('actionsettingdetail','actionid',rid):
            mark('actionsettingdetail',j);params.append(dict(configuration=sanitize(r),value_state='not_collected'))
        java.append(dict(id=rid,registration_key=key,name=val(row,'actionshowname'),action_name=val(row,'actionname'),class_name=val(row,'actionclass'),configuration=sanitize(row),parameters=params,file_keys=code.get(key,{}).get('file_keys',[]),code_lookup_state=code.get(key,{}).get('lookup_state','not_captured'),runtime_verified=False))
    actions=[]
    for i,row in items('workflowactionset'):
        mark('workflowactionset',i);typ=integer(val(row,'interfacetype'));interface=val(row,'interfaceid');matches=[];keys=[]
        if typ==3:
            candidates=[r for _,r in children('actionsetting','actionname',interface)]
            matches=[dict(source='actionsetting',id=val(r,'id')) for r in candidates];keys=['actionsetting:'+str(val(r,'id')) for r in candidates]
        elif typ in [1,2]:
            source={1:'formactionset',2:'wsformactionset'}[typ];rid=integer(interface)
            candidates=[r for _,r in children(source,'id',rid)]
            matches=[dict(source=source,id=val(r,'id')) for r in candidates]
            for r in candidates:
                ctx=context(val(r,'formid'),val(r,'isbill'))
                if ctx!=wfcontext(val(row,'workflowid')):issue('interface_form_context_conflict',source=source,id=val(r,'id'),action_id=val(row,'id'))
        else:issue('interface_type_unexplained',source='workflowactionset',id=val(row,'id'),raw_type=val(row,'interfacetype'))
        if typ in [1,2,3] and not matches:issue('interface_definition_unresolved',source='workflowactionset',id=val(row,'id'))
        if len(matches)>1:issue('interface_definition_ambiguous',source='workflowactionset',id=val(row,'id'))
        actions.append(dict(id=val(row,'id'),configuration=sanitize(row),trigger=trigger(row,'workflowactionset'),interface_type_raw=val(row,'interfacetype'),definition_candidates=matches,code_registration_keys=keys,runtime_verified=False))
    dml=[]
    for source,sqlsource,mapsource,kind in [('formactionset','formactionsqlset','formactionfieldmap','form'),
             ('dmlactionset','dmlactionsqlset','dmlactionfieldmap','legacy_workflow'),('mode_dmlactionset','mode_dmlactionsqlset','mode_dmlactionfieldmap','module')]:
        for i,row in items(source):
            mark(source,i);rid=val(row,'id')
            ctx=context(val(row,'formid'),val(row,'isbill')) if kind=='form' else wfcontext(val(row,'workflowid')) if kind=='legacy_workflow' else modecontext(val(row,'modeid'))
            sqlsets=[]
            for j,s in children(sqlsource,'actionid',rid):
                mark(sqlsource,j);mappings=[]
                for k,m in children(mapsource,'actionsqlsetid',val(s,'id')):
                    mark(mapsource,k);text=str(val(m,'fieldvalue') or '');match=re.fullmatch(r'field(-?[0-9]+)',text)
                    mappings.append(dict(configuration=sanitize(m),source_field_candidate=fieldref(match[1],ctx,mapsource) if match else None,evidence_state='mapping_configuration_raw_codes_unexplained'))
                sqlsets.append(dict(configuration=sanitize(s),mappings=mappings,executed=False))
            dml.append(dict(source=source,id=rid,context=ctx,configuration=sanitize(row),sql_definitions=sqlsets,runtime_verified=False))
    expands=[];all_expands={}
    for source in ['mode_pageexpand','mode_pageexpand_parent']:
        for i,row in items(source):
            mark(source,i);rid=val(row,'id')
            if rid in all_expands:raise ValueError('Duplicate expand definition scope')
            all_expands[rid]=(source,row)
    for rid,(source,row) in all_expands.items():
        details=[]
        for j,d in children('mode_pageexpanddetail','mainid',rid):
            mark('mode_pageexpanddetail',j)
            keyprefix='mode_pageexpanddetail:'+str(val(d,'id'))+':'
            codekeys=[k for k in code if k.startswith(keyprefix)]
            details.append(dict(configuration=sanitize(d),trigger_setting_reference=val(d,'triggerworkflowsetid'),dml_setting_reference=val(d,'dmlactionid'),code_registration_keys=codekeys))
            if val(d,'esbid') or val(d,'taskdetailid'):issue('module_external_definition_pending',source='mode_pageexpanddetail',id=val(d,'id'))
        parent=integer(val(row,'mainid'));pr=all_expands.get(parent)
        if parent and not pr:issue('expand_parent_unresolved',source=source,id=rid,parent_id=parent)
        expands.append(dict(source=source,id=rid,module_id=val(row,'modeid'),configuration=sanitize(row),parent_reference=dict(id=parent,source=pr[0] if pr else None,evidence_state='explicit_mainid_reference_not_inheritance_proof') if parent else None,details=details,runtime_verified=False))
    wftriggers=[]
    for i,row in items('mode_triggerworkflowset'):
        mark('mode_triggerworkflowset',i);rid=val(row,'id');src=modecontext(val(row,'modeid'));dst=wfcontext(val(row,'workflowid'));mappings=[]
        for j,m in children('mode_triggerworkflowsetdetail','mainid',rid):
            mark('mode_triggerworkflowsetdetail',j)
            target=integer(val(m,'wffieldid'));source_field=integer(val(m,'modefieldid'))
            state='target_unselected' if target in [None,0] else 'source_unselected' if source_field in [None,0] else 'configured_target'
            mappings.append(dict(configuration=sanitize(m),mapping_state=state,mapping_state_basis='raw_source_target_field_selection_only_not_execution',
                model_field_reference=fieldref(source_field,src,'mode_triggerworkflowsetdetail_source') if target not in [None,0] else None,
                workflow_field_reference=fieldref(target,dst,'mode_triggerworkflowsetdetail_target')))
        wftriggers.append(dict(id=rid,source_context=src,target_context=dst,configuration=sanitize(row),mappings=mappings,runtime_verified=False))
    cube=[]
    for i,row in items('CubeInterfaceConfig'):
        mark('CubeInterfaceConfig',i);rid=val(row,'id');ctx=modecontext(val(row,'modeid'));mappings=[]
        for j,m in children('cubeInterfaceConfigDetail','mainid',rid):
            mark('cubeInterfaceConfigDetail',j);mappings.append(dict(configuration=sanitize(m),field_reference=fieldref(val(m,'fieldid'),ctx,'cubeInterfaceConfigDetail'),business_key_flag_raw=val(m,'isPK')))
        cube.append(dict(id=rid,configuration=sanitize(row),context=ctx,mappings=mappings,runtime_verified=False))
    other=[]
    for source,childsource in [('wsformactionset',None),('wsactionset',None),('sapactionset','sapactionsetdetail'),('mode_wsactionset',None),('mode_sapactionset','mode_sapactionsetdetail')]:
        for i,row in items(source):
            mark(source,i);sub=[]
            if childsource:
                for j,c in children(childsource,'mainid',val(row,'id')):mark(childsource,j);sub.append(sanitize(c))
            other.append(dict(source=source,id=val(row,'id'),configuration=sanitize(row),children=sub,trigger=trigger(row,source) if source in ['wsactionset','sapactionset'] else None,runtime_verified=False))
    unassociated=[];coverage={}
    for source,rows in tables.items():
        independent=source.startswith(('B03_','B05_','B06_','B07_')) or source in ['modeinfo','local_source_files']
        for i,row in enumerate(rows):
            if not independent and i not in used[source]:unassociated.append(dict(source=source,source_record_index=i,configuration=sanitize(row)));issue('interface_configuration_unassociated',source=source,source_record_index=i)
        coverage[source]=dict(raw_records=len(rows),represented_records=len(rows),associated_records=len(rows) if independent else len(used[source]),role='dependency_validation' if source.startswith(('B03_','B05_','B06_','B07_')) else 'local_code_evidence' if source=='local_source_files' else 'configuration_catalog')
    sqlrefs=[];sqlwarnings=[]
    for source,rows in tables.items():
        if source.startswith(('B03_','B05_','B06_','B07_')) or source=='local_source_files':continue
        for i,row in enumerate(rows):
            for key,value in row.items():
                if key.casefold() not in ['dmlsql','dmlothersql','dmlcuswhere','dmlcussql','showcondition','showcondition2','tipsql','searchsqlwhere'] or not value:continue
                parsed=table_references(str(value))
                parent_source={'formactionsqlset':'formactionset','dmlactionsqlset':'dmlactionset','mode_dmlactionsqlset':'mode_dmlactionset'}.get(source)
                data_source=val(row,'datasourceid');context_known=True;ds_context=None
                if parent_source:
                    parents=children(parent_source,'id',val(row,'actionid'));context_known=len(parents)==1
                    data_source=val(parents[0][1],'datasourceid') if context_known else None
                    ds_context=dict(source=parent_source,id=val(row,'actionid'),datasource_id=data_source,state='parent_matched' if context_known else 'parent_missing_or_ambiguous')
                for ref in parsed['candidates']:
                    local=context_known and not data_source and not val(row,'tipdatasourceid') and not ref['server'] and (not ref['database'] or ref['database'].casefold()==seed.get('_source_database','').casefold())
                    sqlrefs.append(dict(ref,source=source,source_record_index=i,source_id=val(row,'id'),field=key,datasource_context_reference=ds_context,local_database_candidate=local,executed=False))
                if parsed['warnings']:sqlwarnings.append(dict(source=source,id=val(row,'id'),field=key,warnings=parsed['warnings']))
    flows=[]
    for wid,w in workflows.items():
        flowactions=[a['id'] for a in actions if a['trigger']['workflow_id']==wid]
        reach=next((x.get('reachable_model_ids',[]) for x in seed['B06'].get('workflow_links',[]) if x['id']==wid),[])
        flows.append(dict(id=wid,name=w['name'],action_ids=flowactions,reachable_module_candidates=reach,trigger_from_module_ids=[val(t['configuration'],'modeid') for t in wftriggers if integer(val(t['configuration'],'workflowid'))==wid]))
    return sanitize(dict(category='B08',normalization_version='1.0.0',semantic_state='partial_pending_confirmation',runtime_verified=False,business_rows_read=0,
        workflow_actions=actions,java_registrations=java,dml_definitions=dml,module_expansions=expands,workflow_triggers=wftriggers,cube_interfaces=cube,other_interfaces=other,
        workflow_links=flows,models=[dict(id=mid,name=val(row,'modename'),form_id=val(row,'formid'),configuration=row) for mid,row in models.items()],
        local_source_files=tables.get('local_source_files',[]),source_graph=sourcegraph,configuration_catalogs={n:v for n,v in tables.items() if n!='local_source_files' and not n.startswith(('B03_','B05_','B06_','B07_'))},
        sql_source_candidates=sqlrefs,sql_scan_warnings=sqlwarnings,source_coverage=coverage,unassociated_configurations=unassociated,issues=issues,
        summary=dict(workflow_count=len(flows),workflow_action_count=len(actions),java_registration_count=len(java),dml_definition_count=len(dml),module_expand_count=len(expands),
                     module_expand_detail_count=sum(len(x['details']) for x in expands),workflow_trigger_count=len(wftriggers),trigger_mapping_count=sum(len(x['mappings']) for x in wftriggers),
                     trigger_configured_target_count=sum(x['mapping_state']!='target_unselected' for t in wftriggers for x in t['mappings']),trigger_unselected_target_count=sum(x['mapping_state']=='target_unselected' for t in wftriggers for x in t['mappings']),
                     cube_interface_count=len(cube),cube_mapping_count=sum(len(x['mappings']) for x in cube),local_source_file_count=len(tables.get('local_source_files',[])),issue_counts=dict(Counter(x['kind'] for x in issues))),
        limitations=['只读静态定义和本机文件；没有调用接口、执行SQL/Java或读取业务单据/执行日志。','接口注册存在、配置开关、代码条件、线上加载和实际成功是不同结论。',
                     '任意Action属性值和API密钥未读取；XML/URL/代码中明显凭据遮蔽，不求值动态秘密。','DML映射码、共享mainid、部分内置字段及外部/ESB/任务定义保持待解释。',
                     '源码词法和class常量池只提供候选，未恢复完整控制流、事务、幂等或恢复路径；return SUCCESS不等于外部交易成功。']))
