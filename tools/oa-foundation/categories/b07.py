"""B07 report/search definitions. No SQL evaluation or business rows."""
import re
from collections import defaultdict,Counter
from .b05 import safe,val,integer
from sql_refs import table_references

KINDS={
 'workflow_standard':('Workflow_Report','Workflow_ReportDspField','reportid','WorkflowReportShare'),
 'workflow_custom':('workflow_customreport','workflow_customreport_field','reportid','workflow_customreport_share'),
 'model_report':('mode_report','mode_ReportDspField','reportid','mode_reportshareinfo'),
 'model_search':('mode_customsearch','mode_CustomDspField','customid','mode_searchPageshareinfo')}
def normalize(tables,seed):
    issues=[];reports=[];unassociated=[];used=defaultdict(set)
    def issue(kind,**where):issues.append(dict(kind=kind,**where))
    def rows(name):return list(enumerate(tables.get(name,[])))
    def cover(name,i):used[name].add(i)
    fields=defaultdict(list)
    for f in seed['B06']['dictionary']['fields']:fields[(f['form_source'],f['form_id'],f['field_id'])].append(f)
    models={x['id']:x for x in seed['B06']['models']}
    models.update({val(x,'id'):dict(id=val(x,'id'),name=val(x,'modename'),configuration=x) for x in tables.get('modeinfo',[])})
    independent={'ModeFormExtend','Workflow_ReportType','modeinfo','Workflow_Report_scope','workflow_customreport_scope'}
    workflows={w['id']:w for w in seed['workflows']}
    def fieldref(raw,report,where):
        fid=integer(raw)
        if fid is None:issue('report_field_reference_unparsed',report_key=report['key'],source=where,raw=raw);return None
        if fid<=0:return dict(namespace='report_internal_unverified',field_id=fid,semantics='保留报表自身内置编号，未套用工作流内置字典')
        candidates=fields[(report['form_source'],report['form_id'],fid)]
        if len(candidates)!=1:issue('report_field_unresolved',report_key=report['key'],source=where,field_id=fid);return None
        return dict(candidates[0],namespace='form_field')
    for kind,(source,fieldsource,parentkey,share_source) in KINDS.items():
        seen=set()
        for pos,row in rows(source):
            rid=val(row,'id')
            if rid in seen:raise ValueError('Duplicate report definition: '+source)
            seen.add(rid);cover(source,pos)
            formid=integer(val(row,'formid'));modeid=integer(val(row,'modeid'));model=models.get(modeid)
            formsource='workflow_bill' if kind.startswith('model_') else {0:'workflow_formbase',1:'workflow_bill'}.get(integer(val(row,'isbill')))
            basis='report_explicit'
            if kind.startswith('model_') and formid in [None,0] and model:
                formid=integer(val(model['configuration'],'formid'));basis='module_reference_fallback'
            r=dict(kind=kind,id=rid,key=kind+':'+str(rid),name=val(row,'reportname') or val(row,'customname') or '未命名',
                   configuration=safe(row),form_source=formsource,form_id=formid,form_basis=basis,
                   model_id=modeid,model_reference=(dict(id=model['id'],name=model['name']) if model else None),
                   fields=[],permissions=[],calculations=[],saved_filters=[],other_definitions=[],
                   workflow_list_state='not_applicable',explicit_workflow_ids=[],form_workflow_candidates=[],
                   model_reference_workflow_candidates=[x['id'] for x in seed['B06'].get('workflow_links',[]) if modeid is not None and modeid in x.get('reachable_model_ids',[])],
                   runtime_verified=False)
            if kind.startswith('model_') and modeid and not model:issue('report_model_definition_unresolved',report_key=r['key'],model_id=modeid)
            if model and integer(val(model['configuration'],'formid'))!=formid:issue('report_model_form_conflict',report_key=r['key'],model_id=modeid)
            if kind.startswith('workflow_'):
                text=str(val(row,'reportwfid' if kind=='workflow_standard' else 'workflowid') or '').strip()
                if not text:r['workflow_list_state']='empty'
                elif re.fullmatch(r'\s*[0-9]+\s*(?:,\s*[0-9]+\s*)*',text) and all(int(x.strip())<=2147483647 for x in text.split(',')):
                    r['workflow_list_state']='parsed';r['explicit_workflow_ids']=list(dict.fromkeys(int(x.strip()) for x in text.split(',')))
                else:r['workflow_list_state']='unparsed';issue('report_workflow_list_unparsed',report_key=r['key'])
                for wid in r['explicit_workflow_ids']:
                    w=workflows.get(wid)
                    if not w:issue('report_workflow_unresolved',report_key=r['key'],workflow_id=wid)
                    elif (w['form_source'],w['form_id'])!=(formsource,formid):issue('report_workflow_form_conflict',report_key=r['key'],workflow_id=wid)
            r['form_workflow_candidates']=[w['id'] for w in workflows.values() if (w['form_source'],w['form_id'])==(formsource,formid)]
            for i,c in rows(fieldsource):
                if val(c,parentkey)==rid:
                    cover(fieldsource,i)
                    current=val(c,'fieldid');backup=val(c,'fieldidbak')
                    r['fields'].append(dict(source=fieldsource,source_record_index=i,configuration=safe(c),
                        field_reference=fieldref(current,r,fieldsource) if current is not None else None,
                        backup_field_reference=fieldref(backup,r,fieldsource+'_backup') if current is None and backup is not None else None,
                        field_state='current_binding_absent_backup_retained' if current is None and backup is not None else 'current_binding_absent' if current is None else 'current_binding_present'))
            for i,c in rows(share_source):
                if val(c,'pageid' if kind=='model_search' else 'reportid')==rid:
                    cover(share_source,i);r['permissions'].append(dict(source=share_source,source_record_index=i,configuration=safe(c),semantics='配置原值；未展开当前用户权限'))
            for i,c in rows('workflow_report_competence'):
                if kind.startswith('workflow_') and integer(val(c,'formid'))==formid and integer(val(c,'isbill'))==integer(val(row,'isbill')):
                    cover('workflow_report_competence',i);r['permissions'].append(dict(source='workflow_report_competence',source_record_index=i,configuration=safe(c),semantics='表单维度权限候选；不等于报表共享'))
            if kind=='workflow_custom':
                for i,c in rows('workflow_customreport_project'):
                    if val(c,'reportid')==rid:
                        cover('workflow_customreport_project',i);r['calculations'].append(dict(source='workflow_customreport_project',source_record_index=i,configuration=safe(c),evidence_state='expression_not_evaluated'))
            template_source='WorkflowRptCondMould' if kind=='workflow_standard' else 'workflow_customreport_template' if kind=='workflow_custom' else None
            if template_source:
                detail_source='WorkflowRptCondMouldDetail' if kind=='workflow_standard' else 'workflow_customreport_tfield'
                for i,c in rows(template_source):
                    if val(c,'reportid')!=rid:continue
                    cover(template_source,i);r['other_definitions'].append(dict(source=template_source,source_record_index=i,configuration=safe(c)))
                    for j,d in rows(detail_source):
                        if val(d,'mouldid' if kind=='workflow_standard' else 'templateid')!=val(c,'id'):continue
                        cover(detail_source,j);r['saved_filters'].append(dict(source=detail_source,source_record_index=j,parent_configuration=safe(c),configuration=safe(d),field_reference=fieldref(val(d,'fieldid'),r,detail_source)))
            if kind=='model_search':
                for other in ['mode_customsearchgroup','mode_quicksearch_condition']:
                    for i,c in rows(other):
                        if val(c,'customid')==rid:
                            cover(other,i);item=dict(source=other,source_record_index=i,configuration=safe(c))
                            if other=='mode_quicksearch_condition':item['field_reference']=fieldref(val(c,'fieldid'),r,other)
                            r['other_definitions'].append(item)
            physical_tables={x['field_reference'].get('physical_table') for x in r['fields'] if x['field_reference'] and (integer(val(x['field_reference'].get('configuration',{}),'viewtype'))==1 or val(x['field_reference'].get('binding',{}),'isdetail')=='1') and x['field_reference'].get('physical_table')}
            if len(physical_tables)>1 and any(str(val(x['configuration'],'isstat'))=='1' for x in r['fields']):
                issue('multiple_detail_aggregation_review',report_key=r['key'],detail_tables=sorted(physical_tables))
            reports.append(r)
    # Definitions without a selected parent are retained separately, never silently discarded.
    for source,items in tables.items():
        if source.startswith('B06_'):continue
        if source in independent:continue
        for i,row in enumerate(items):
            if i not in used[source]:
                unassociated.append(dict(source=source,source_record_index=i,configuration=safe(row)))
                issue('report_configuration_unassociated',source=source,source_record_index=i)
    sqlrefs=[];sqlwarnings=[]
    for source,items in tables.items():
        if source.startswith('B06_'):continue
        for i,row in enumerate(items):
            for k,text in row.items():
                if k.casefold() not in ['defaultsql','conditionsql','conditionsqltop','defaultsqltop','vsql']:continue
                if not text:continue
                datasource=val(row,'vdatasource') if source=='ModeFormExtend' else None
                parsed=table_references(str(text));refs=parsed['candidates'];warnings=parsed['warnings']
                refs=[dict(x,local_database_candidate=not datasource and not x['server'] and (not x['database'] or x['database'].casefold()==seed.get('_source_database','').casefold()),executed=False) for x in refs]
                context=dict(source=source,source_record_index=i,source_id=val(row,'id') if val(row,'id') is not None else val(row,'formid'),field=k)
                sqlrefs += [dict(x,**context) for x in refs]
                sqlwarnings += [dict(warning=x,**context) for x in warnings]
    coverage={name:dict(raw_records=len(items),represented_records=len(items),associated_records=(len(items) if name.startswith('B06_') or name in independent else len(used[name])),role='dependency_validation' if name.startswith('B06_') else 'scope_selection_directory' if name.endswith('_scope') else 'configuration_catalog') for name,items in tables.items()}
    return safe(dict(category='B07',normalization_version='1.0.0',semantic_state='partial_pending_confirmation',business_rows_read=0,runtime_verified=False,
        reports=reports,virtual_forms=[dict(configuration=row,evidence_state='definition_only_not_executed') for row in tables.get('ModeFormExtend',[])],
        configuration_catalogs={n:v for n,v in tables.items() if not n.startswith('B06_')},sql_source_candidates=sqlrefs,sql_scan_warnings=sqlwarnings,
        source_coverage=coverage,unassociated_configurations=unassociated,issues=issues,
        summary=dict(report_count=len(reports),counts={kind:sum(r['kind']==kind for r in reports) for kind in KINDS},field_count=sum(len(r['fields']) for r in reports),backup_field_count=sum(x['field_state']=='current_binding_absent_backup_retained' for r in reports for x in r['fields']),permission_count=sum(len(r['permissions']) for r in reports),
                     calculation_count=sum(len(r['calculations']) for r in reports),saved_filter_count=sum(len(r['saved_filters']) for r in reports),virtual_form_count=len(tables.get('ModeFormExtend',[])),issue_counts=dict(Counter(x['kind'] for x in issues))),
        limitations=['仅配置定义，SQL、公式、Java扩展和URL均未执行；业务行读取0。','流程列表、表单共享和模块引用分别记录，不等于实际使用。','权限是共享/表单配置原值；未读取逐人派生权限或证明实际可见范围。',
                     'SQL只有词法来源候选，未验证列级血缘、动态条件、汇总粒度及运行值。','老式静态报表入口的配置/过程定义尚不可见，非本工具已完整覆盖全部平台报表。','字段/过滤值可能依赖用户、日期和扩展程序，语义及启停编码待校准。']))
