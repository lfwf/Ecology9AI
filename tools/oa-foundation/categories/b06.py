"""B06 referenced browser/model configuration and physical dictionaries. No business reads."""
import re
from collections import Counter,defaultdict,deque
from copy import deepcopy
from . import b02
from .b05 import safe,val,integer
from sql_refs import table_references,split_identifier
CATEGORY='B06'
NORMALIZATION_VERSION='1.0.0'
def normalize(tables,seed):
    issues=[];edges=[];unassociated=[]
    def issue(kind,**refs):issues.append(dict(kind=kind,**refs))
    def index(name):
        result={}
        for row in tables.get(name,[]):
            rid=val(row,'id')
            if rid in result:raise ValueError('Duplicate configuration key: '+name)
            result[rid]=row
        return result
    def edge(a,b,kind,source=None,state='configuration_reference'):
        edges.append(dict(source_node=a,target_node=b,relation=kind,evidence=source,state=state,runtime_verified=False))
    raw_bills=index('workflow_bill');raw_models=index('modeinfo');customs=index('mode_custombrowser');settings=index('mode_workflowtomodeset')
    declarations=set()
    for row in raw_bills.values():
        for name in ['tablename','detailtablename']:
            if val(row,name):declarations.add(val(row,name))
    for row in tables.get('Workflow_billdetailtable',[]):
        if val(row,'tablename'):declarations.add(val(row,'tablename'))
    for row in tables.get('workflow_billfield',[]):
        if val(row,'detailtable'):declarations.add(val(row,'detailtable'))
    if tables.get('B02_workflow_formbase'):declarations.update(['workflow_form','workflow_formdetail'])
    physical_by_name=defaultdict(set)
    for row in tables.get('physical_columns',[]):physical_by_name[row['table_name'].casefold()].add((row.get('schema_name','dbo'),row['table_name']))
    resolutions={}
    for declared in sorted(declarations):
        parsed=split_identifier(declared)
        if not parsed or parsed['server'] or (parsed['database'] and parsed['database'].casefold()!=seed.get('_source_database','').casefold()):
            resolutions[declared]=dict(declared_name=declared,state='external_or_unparsed',schema=None,object_name=None);issue('physical_identifier_unresolved',declared_name=declared);continue
        candidates=physical_by_name[parsed['object_name'].casefold()]
        if parsed['schema']:candidates={x for x in candidates if x[0].casefold()==parsed['schema'].casefold()}
        exact={x for x in candidates if x[1]==parsed['object_name'] and (not parsed['schema'] or x[0]==parsed['schema'])}
        if exact:candidates=exact
        if len(candidates)==1:
            schema,name=next(iter(candidates));resolutions[declared]=dict(declared_name=declared,state='resolved',schema=schema,object_name=name)
        else:
            state='ambiguous' if candidates else 'not_visible_in_captured_metadata'
            resolutions[declared]=dict(declared_name=declared,state=state,schema=None,object_name=parsed['object_name'],candidates=sorted(candidates))
            issue('physical_schema_ambiguous' if candidates else 'physical_object_not_visible',declared_name=declared)
    adapted_columns=[];adapted_keys=[];adapted_case={}
    for declared,resolution in resolutions.items():
        if resolution['state']!='resolved':continue
        folded=declared.casefold();actual=(resolution['schema'],resolution['object_name'])
        if folded in adapted_case:
            if adapted_case[folded]!=actual:
                issue('physical_case_sensitive_collision',declared_name=declared)
                adapted_columns=[r for r in adapted_columns if r['table_name'].casefold()!=folded];adapted_keys=[r for r in adapted_keys if r['table_name'].casefold()!=folded]
            continue
        adapted_case[folded]=actual
        for row in tables.get('physical_columns',[]):
            if (row.get('schema_name','dbo'),row['table_name'])==actual:adapted_columns.append(dict(row,table_name=declared))
        for row in tables.get('physical_keys',[]):
            if (row.get('schema_name','dbo'),row['table_name'])==actual:adapted_keys.append(dict(row,table_name=declared))
    dictionary_tables=dict(tables,physical_columns=adapted_columns,physical_keys=adapted_keys)
    for name in ['workflow_formbase','workflow_formfield','workflow_formdict','workflow_formdictdetail','workflow_fieldlable']:
        dictionary_tables[name]=tables.get('B02_'+name,tables.get(name,[]))
    # Anchors include legacy namespace lookups absent from bill-only expansion.
    for name in ['workflow_SelectItem','workflow_browserurl','workflow_browsertype']:
        current=list(dictionary_tables.get(name,[]));by_id={}
        for row in current:
            if row['id'] in by_id:raise ValueError('Duplicate lookup definition: '+name)
            by_id[row['id']]=row
        for row in tables.get('B02_'+name,[]):
            if row['id'] not in by_id:current.append(row);by_id[row['id']]=row
            elif by_id[row['id']]!=row:raise ValueError('Lookup anchor disagreement: '+name)
        dictionary_tables[name]=current
    dictionary_seed=dict(seed,additional_form_scopes=[dict(form_source='workflow_bill',form_id=fid) for fid in raw_bills])
    dictionary=b02.normalize(dictionary_tables,dictionary_seed)
    forms={(f['form_source'],f['form_id']):f for f in dictionary['forms']}
    field_index=defaultdict(list)
    for f in dictionary['fields']:field_index[(f['form_source'],f['form_id'],f['field_id'])].append(f)
    # Input workflow references may also use a legacy form namespace.
    for f in seed.get('B02',{}).get('fields',[]):
        key=(f['form_source'],f['form_id'],f['field_id'])
        if key not in field_index:field_index[key].append(f)
    def field_ref(namespace,form_id,field_id,source):
        fid=integer(field_id)
        matches=field_index.get((namespace,form_id,fid),[])
        if len(matches)!=1:
            if fid not in [None,0]:issue('referenced_field_unresolved',source=source,form_source=namespace,form_id=form_id,field_id=fid)
            return None
        return {k:matches[0].get(k) for k in ['form_source','form_id','field_id','name','physical_table','column_name','physical_sql_type']}
    def form_ref(form_id):
        form=forms.get(('workflow_bill',form_id))
        return {k:form.get(k) for k in ['form_source','form_id','name','main_table','details']} if form else None
    unique_single=set();key_groups=defaultdict(list)
    for row in adapted_keys:key_groups[(row['table_name'].casefold(),row['index_name'])].append(row)
    for (table,_),rows in key_groups.items():
        if len(rows)==1 and rows[0]['is_unique'] and not rows[0]['has_filter'] and rows[0].get('is_disabled') is False and rows[0].get('is_hypothetical') is False:
            unique_single.add((table,rows[0]['column_name'].casefold()))
    # Re-evaluate FK evidence using resolved schemas, rather than assuming dbo.
    fk_groups=defaultdict(list)
    for row in tables.get('physical_foreign_keys',[]):fk_groups[(row.get('child_schema','dbo'),row['child_table'],row['constraint_name'])].append(row)
    for relation in dictionary['relationships']:
        p=resolutions.get(relation['parent_table'],{});c=resolutions.get(relation['child_table'],{})
        relation['parent_schema_reference']=p.get('schema');relation['child_schema_reference']=c.get('schema')
        relation['database_fk_enforced']=any(len(rows)==1 and rows[0].get('is_disabled') is False and rows[0].get('is_not_trusted') is False
            and (rows[0].get('child_schema','dbo'),rows[0]['child_table'],rows[0]['child_column'])==(c.get('schema'),c.get('object_name'),relation['child_column'])
            and (rows[0].get('parent_schema','dbo'),rows[0]['parent_table'],rows[0]['parent_column'])==(p.get('schema'),p.get('object_name'),relation['parent_column']) for rows in fk_groups.values())
    companies={val(r,'id'):r for r in tables.get('HrmSubCompany',[])}
    models=[]
    for row in raw_models.values():
        fid=val(row,'formid');reference=form_ref(fid)
        if reference is None:issue('model_form_unresolved',model_id=row['id'],form_id=fid)
        models.append(dict(id=row['id'],name=val(row,'modename'),configuration=safe(row),form_reference=reference,
                           subcompany_reference=safe(companies.get(val(row,'subcompanyid'))),runtime_verified=False))
        if reference:
            edge('model:'+str(row['id']),'form:workflow_bill:'+str(fid),'uses_form',dict(source='modeinfo',id=row['id']))
            edge('form:workflow_bill:'+str(fid),'model:'+str(row['id']),'registered_model',dict(source='modeinfo',id=row['id']))
    model_index={m['id']:m for m in models}
    display_by_custom=defaultdict(list)
    for row in tables.get('mode_CustombrowserDspField',[]):display_by_custom[val(row,'customid')].append(row)
    custom_models={}
    for row in customs.values():
        cid=row['id'];fid=val(row,'formid');reference=form_ref(fid);model=model_index.get(val(row,'modeid'))
        if reference is None:issue('custom_browser_form_unresolved',custom_id=cid,form_id=fid)
        if model and model['form_reference'] and model['form_reference']['form_id']!=fid:issue('custom_browser_model_form_difference',custom_id=cid,model_id=model['id'],browser_form_id=fid)
        detail=val(row,'detailtable')
        grain=dict(kind='configured_detail' if detail else 'configured_main',table_name=detail or (reference or {}).get('main_table'),runtime_verified=False)
        fields=[];return_keys=[]
        for display in display_by_custom[cid]:
            raw_id=val(display,'fieldid')
            if integer(raw_id) is not None and integer(raw_id)<0:
                fr=dict(namespace='browser_internal',field_id=raw_id,name=None,semantics_state='uninterpreted_not_workflow_platform_field',physical_table=None,column_name=None)
            else:fr=field_ref('workflow_bill',fid,raw_id,'custom_browser_display')
            entry=dict(configuration=safe(display),field_reference=fr)
            fields.append(entry)
            if val(display,'ispk')==1:
                field_table=(fr or {}).get('physical_table');column=(fr or {}).get('column_name')
                key_state='unique_single_column' if field_table and column and (field_table.casefold(),column.casefold()) in unique_single else 'not_proven_unique'
                return_keys.append(dict(configuration=safe(display),field_reference=fr,physical_key_state=key_state,returned_from_grain=grain['table_name'],runtime_verified=False))
        custom_models[cid]=dict(id=cid,name=val(row,'customname'),configuration=safe(row),form_reference=reference,
            model_reference=dict(id=model['id'],name=model['name']) if model else None,display_fields=fields,return_keys=return_keys,grain_reference=grain,
            key_fallback_state='not_inferred_when_no_explicit_ispk',runtime_verified=False)
        if reference:edge('custom_browser:'+str(cid),'form:workflow_bill:'+str(fid),'selects_form',dict(source='mode_custombrowser',id=cid))
        if model:edge('custom_browser:'+str(cid),'model:'+str(model['id']),'declares_model',dict(source='mode_custombrowser',id=cid))
    registrations=defaultdict(list);all_codes=set()
    for source in ['MODE_BROWSER','datashowset']:
        for row in tables.get(source,[]):
            code=val(row,'showname');all_codes.add(code);custom_id=val(row,'customid')
            custom=custom_models.get(custom_id)
            if custom_id and custom_id>0 and custom is None:issue('custom_browser_definition_unresolved',source=source,id=row['id'],custom_id=custom_id)
            entry=dict(source=source,id=row['id'],configuration=safe(row),custom_browser=custom,priority_state='not_inferred',
                datasource_state='unverified_external_or_named_source' if val(row,'datasourceid') else 'default_database_candidate_not_runtime_proof',runtime_verified=False)
            registrations[code].append(entry)
            node='registry:'+source+':'+str(row['id'])
            edge('browser:'+str(code),node,'has_registration_candidate',dict(source=source,id=row['id']))
            if custom:edge(node,'custom_browser:'+str(custom_id),'declares_custom_browser',dict(source=source,id=row['id']))
    field_browser_links=[]
    for field in dictionary['fields']:
        code=field.get('custom_browser_code')
        if code:
            all_codes.add(code);field_browser_links.append(dict(field_reference={k:field.get(k) for k in ['field_key','form_source','form_id','field_id','name','physical_table','column_name']},code=code))
            edge('form:'+field['form_source']+':'+str(field['form_id']),'browser:'+code,'field_browser',field['source_ref'])
    # Keep codes from a source namespace not present in the extended dictionary.
    for field in seed.get('B02',{}).get('fields',[]):
        code=field.get('custom_browser_code')
        if code:all_codes.add(code)
    browsers=[]
    for code in sorted(all_codes):
        found=registrations.get(code,[])
        state='multiple_registrations_pending_priority' if len(found)>1 else 'registration_captured_semantics_pending' if found else 'missing_in_visible_registries'
        if not found:issue('browser_code_unresolved',code=code)
        browsers.append(dict(code=code,lookup_state=state,registrations=found,runtime_verified=False))
    # Keep all original dictionary issues except references resolved by this category.
    for item in dictionary['issues']:
        if item['kind']=='custom_browser_definition_pending' and registrations.get(item['browser_code']):continue
        issues.append(dict(item,area='dictionary'))
    sql_candidates=[];sql_warnings=[]
    for source in ['MODE_BROWSER','datashowset']:
        for row in tables.get(source,[]):
            for column in ['sqltext','sqltext1','sqltext2','searchById','searchByName']:
                text=val(row,column)
                if not text:continue
                parsed=table_references(text)
                for ref in parsed['candidates']:
                    local=not val(row,'datasourceid') and not ref['server'] and (not ref['database'] or ref['database'].casefold()==seed.get('_source_database','').casefold())
                    sql_candidates.append(dict(ref,source=source,source_id=row['id'],field=column,local_database_candidate=local,executed=False))
                if parsed['warnings']:sql_warnings.append(dict(source=source,id=row['id'],field=column,warnings=parsed['warnings']))
    by_entry={val(r,'id'):r for r in tables.get('B05_workflow_datainput_entry',[])}
    by_query={val(r,'id'):r for r in tables.get('B05_workflow_datainput_main',[])}
    input_sources=[]
    for row in tables.get('B05_workflow_datainput_table',[]):
        query=by_query.get(val(row,'datainputid'));entry=by_entry.get(val(query,'entryid'))
        parsed=split_identifier(val(row,'tablename'))
        input_sources.append(dict(configuration=safe(row),query_reference=safe(query),workflow_id=val(entry,'workflowid'),
            identifier_candidate=parsed,datasource_name=val(query,'datasourcename'),source_verified=False,business_rows_read=0))
    flow_index={w['id']:w for w in seed['workflows']};mapping_children=defaultdict(list);operations=defaultdict(list)
    for row in tables.get('mode_workflowtomodesetdetail',[]):mapping_children[val(row,'mainid')].append(row)
    for row in tables.get('mode_workflowtomodesetopt',[]):operations[val(row,'mainid')].append(row)
    action_origins=defaultdict(list)
    for action in tables.get('B05_workflow_addinoperate',[]):
        text=str(val(action,'wftomodesetid') or '').strip()
        if not text:continue
        parts=[x for x in re.split(r'[,;\s]+',text) if x]
        if any(not re.fullmatch(r'\d+',x) for x in parts):
            issue('action_setting_reference_syntax_unknown',action_id=val(action,'id'));continue
        for token in parts:
            sid=int(token)
            if sid>0:action_origins[sid].append(dict(action_id=val(action,'id'),workflow_id=val(action,'workflowid')))
    setting_models=[]
    for row in settings.values():
        sid=row['id'];wid=val(row,'workflowid');workflow=flow_index.get(wid);model=model_index.get(val(row,'modeid'))
        origins=action_origins[sid];origin_ids=sorted({o['workflow_id'] for o in origins if o['workflow_id'] in flow_index})
        basis='declared_workflow_id' if workflow else 'unresolved'
        if workflow is None and len(origin_ids)==1:workflow=flow_index[origin_ids[0]];basis='unique_action_reference_candidate'
        if workflow and any(candidate!=workflow['id'] for candidate in origin_ids):issue('setting_workflow_reference_conflict',setting_id=sid,declared_workflow_id=wid,action_workflow_ids=origin_ids)
        target_form=(model or {}).get('form_reference');mappings=[]
        if model is None:issue('setting_model_unresolved',setting_id=sid,model_id=val(row,'modeid'))
        if workflow is None:issue('setting_workflow_context_unresolved',setting_id=sid,workflow_id=wid)
        for mapping in mapping_children[sid]:
            source_id=integer(val(mapping,'wffieldid'))
            source_ref=field_ref(workflow['form_source'],workflow['form_id'],source_id,'workflow_to_model_source') if workflow and source_id is not None and source_id>0 else None
            candidate_mappings=[]
            for candidate_id in origin_ids:
                if workflow and candidate_id==workflow['id']:continue
                context=flow_index[candidate_id]
                candidate_mappings.append(dict(workflow_id=candidate_id,basis='action_reference_candidate',field_reference=field_ref(context['form_source'],context['form_id'],source_id,'action_workflow_to_model_source') if source_id is not None and source_id>0 else None))
            target_id=integer(val(mapping,'modefieldid'));target_ref=field_ref('workflow_bill',target_form['form_id'],target_id,'workflow_to_model_target') if target_form and target_id is not None and target_id>0 else None
            mappings.append(dict(configuration=safe(mapping),workflow_field_reference=source_ref,model_field_reference=target_ref,candidate_workflow_mappings=candidate_mappings,workflow_source_kind='configured_field' if source_id is not None and source_id>0 else 'internal_or_constant_uninterpreted',model_target_kind='configured_field' if target_id is not None and target_id>0 else 'internal_uninterpreted',default_value_not_executed=True))
        setting_models.append(dict(id=sid,configuration=safe(row),workflow_reference=dict(id=workflow['id'],name=workflow['name']) if workflow else None,workflow_reference_basis=basis,action_reference_origins=origins,
            model_reference=dict(id=model['id'],name=model['name']) if model else None,form_reference=target_form,mappings=mappings,detail_operations=safe(operations[sid]),executed=False))
        if workflow and model:edge('workflow:'+str(workflow['id']),'model:'+str(model['id']),'configured_workflow_to_model',dict(source='mode_workflowtomodeset',id=sid))
        if model:
            for origin in origins:
                if origin['workflow_id'] in flow_index:edge('workflow:'+str(origin['workflow_id']),'model:'+str(model['id']),'action_setting_reference',dict(source='B05_workflow_addinoperate',id=origin['action_id'],setting_id=sid),state='explicit_action_reference_candidate')
    for source in ['mode_workflowtomodesetdetail','mode_workflowtomodesetopt']:
        for i,row in enumerate(tables.get(source,[])):
            if val(row,'mainid') not in settings:
                issue('setting_child_unassociated',source=source,source_record_index=i)
                unassociated.append(dict(source=source,source_record_index=i,configuration=safe(row)))
    for workflow in seed['workflows']:
        edge('workflow:'+str(workflow['id']),'form:'+workflow['form_source']+':'+str(workflow['form_id']),'uses_workflow_form',dict(source='B01',id=workflow['id']))
    adjacent=defaultdict(list)
    for e in edges:adjacent[e['source_node']].append(e['target_node'])
    workflow_links=[]
    for workflow in seed['workflows']:
        queue=deque(['workflow:'+str(workflow['id'])]);visited=set()
        while queue:
            current=queue.popleft()
            if current in visited:continue
            visited.add(current);queue.extend(adjacent[current])
        reached=sorted(int(n.split(':')[1]) for n in visited if n.startswith('model:'))
        workflow_links.append(dict(id=workflow['id'],name=workflow['name'],reachable_model_ids=reached,visited_reference_count=len(visited),runtime_verified=False))
    catalogs={name:safe(rows) for name,rows in tables.items() if not name.startswith(('B02_','B05_','physical_'))}
    coverage={name:dict(raw_records=len(rows),represented_records=len(rows),
        role='dependency_validation' if name.startswith(('B02_','B05_')) else 'physical_metadata' if name.startswith('physical_') else 'configuration_catalog') for name,rows in tables.items()}
    return dict(category=CATEGORY,normalization_version=NORMALIZATION_VERSION,semantic_state='partial_pending_confirmation',runtime_verified=False,business_rows_read=0,
        dictionary=safe(dictionary),models=models,browsers=browsers,field_browser_links=safe(field_browser_links),workflow_model_settings=setting_models,
        workflow_links=workflow_links,reference_edges=safe(edges),physical_object_resolutions=list(resolutions.values()),
        physical_metadata={n:safe(tables.get(n,[])) for n in ['physical_columns','physical_keys','physical_foreign_keys']},
        configuration_catalogs=catalogs,sql_source_candidates=safe(sql_candidates),sql_scan_warnings=sql_warnings,input_sources=input_sources,
        source_coverage=coverage,unassociated_configurations=unassociated,issues=issues,
        limitations=['只整理注册、模块、字段映射与系统结构；没有读取UF/表单业务记录或执行浏览框SQL。','新旧注册与同名候选分别保留，未验证服务装载和实际优先级。','SQL对象仅词法候选；外部数据源不连接，本地同名表不证明是外部数据来源。','浏览框内置字段与流程平台负字段分开，未解释的返回默认键不猜测。','结构唯一索引和主明细配置不能证明实际行粒度、重复键、孤立数据或跨公司同码。','各类别采集时点分别记录，依赖锚点一致不等于事务级快照。'],
        summary=dict(workflow_count=len(workflow_links),model_count=len(models),form_count=len(dictionary['forms']),field_count=len(dictionary['fields']),
            browser_code_count=len(browsers),registration_count=sum(len(b['registrations']) for b in browsers),custom_browser_count=len(custom_models),
            workflow_model_setting_count=len(setting_models),workflow_model_field_mapping_count=sum(len(s['mappings']) for s in setting_models),
            source_count=len(tables),issue_counts=dict(Counter(i['kind'] for i in issues))))
