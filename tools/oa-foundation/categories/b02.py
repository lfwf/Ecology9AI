"""B02 configuration/physical-schema mapping. Never reads business records."""
import re
from collections import Counter,defaultdict

CATEGORY='B02'
NORMALIZATION_VERSION='1.0.0'

def physical_sql_type(column):
    if not column:return None
    name=column['data_type'].lower()
    if name in ['varchar','char','nvarchar','nchar','varbinary','binary']:
        length=column['max_length']
        value='max' if length==-1 else str(length//2 if name in ['nvarchar','nchar'] else length)
        return name+'('+value+')'
    if name in ['decimal','numeric']:return name+'('+str(column['precision'])+','+str(column['scale'])+')'
    if name in ['datetime2','time','datetimeoffset']:return name+'('+str(column['scale'])+')'
    return name


def normalize(tables,seed):
    issues=[]; fields=[]; forms=[]; relationships=[]
    def issue(kind,**refs): issues.append(dict(kind=kind,**refs))
    def index(name):
        result={}
        for row in tables.get(name,[]):
            if row['id'] in result: raise ValueError('Duplicate definition ID: '+name)
            result[row['id']]=row
        return result
    bills=index('workflow_bill')
    oldforms=index('workflow_formbase')
    billfields=tables.get('workflow_billfield',[])
    oldmain=index('workflow_formdict'); olddetail=index('workflow_formdictdetail')
    labels=defaultdict(set)
    for row in tables.get('HtmlLabelInfo',[]):
        if row['languageid']==7 and row['labelname']:labels[row['indexid']].add(row['labelname'])
    oldlabels=defaultdict(set)
    for row in tables.get('workflow_fieldlable',[]):
        if row['langurageid']==7 and row['fieldlable']:oldlabels[(row['formid'],row['fieldid'])].add(row['fieldlable'])
    columns=defaultdict(dict)
    for row in tables.get('physical_columns',[]):
        key=row['table_name'].casefold(); name=row['column_name'].casefold()
        if name in columns[key]: raise ValueError('Ambiguous physical column')
        columns[key][name]=row
    indexes=defaultdict(list)
    for row in tables.get('physical_keys',[]):
        indexes[(row['table_name'].casefold(),row['index_name'])].append(row)
    unique_single=set()
    for (table,_),rows in indexes.items():
        if len(rows)==1 and rows[0]['is_unique'] and not rows[0]['has_filter'] and rows[0].get('is_disabled') is False and rows[0].get('is_hypothetical') is False:
            unique_single.add((table,rows[0]['column_name'].casefold()))
    workflow_refs=defaultdict(list)
    for workflow in seed['workflows']:
        workflow_refs[(workflow['isbill_raw'],workflow['form_id'])].append(workflow['id'])
    for scope in seed.get('additional_form_scopes',[]):
        selector={'workflow_bill':'1','workflow_formbase':'0'}.get(scope['form_source'])
        if selector is None:raise ValueError('Unknown additional form namespace')
        workflow_refs.setdefault((selector,scope['form_id']),[])
    options=defaultdict(list)
    for row in tables.get('workflow_SelectItem',[]): options[(str(row['isbill']),row['fieldid'])].append(row)
    browsers=index('workflow_browserurl')

    def label(values,fallback,refs):
        if len(values)==1:return next(iter(values)),'resolved'
        state='ambiguous' if values else 'missing'
        issue('label_'+state,**refs)
        return fallback,state

    def add_field(source,form,table,selector,field_id,label_values,group=None):
        ref=dict(form_id=form['form_id'],form_source=form['form_source'],field_id=field_id)
        name,state=label(label_values,source.get('fieldname') or str(field_id),ref)
        physical=columns.get((table or '').casefold(),{}).get((source.get('fieldname') or '').casefold())
        if not physical:issue('configured_column_not_found',table=table,column=source.get('fieldname'),**ref)
        declared=source.get('fielddbtype')
        custom_browser=declared[len('browser.'):] if isinstance(declared,str) and declared.startswith('browser.') else None
        if custom_browser:issue('custom_browser_definition_pending',browser_code=custom_browser,**ref)
        if physical and declared and not custom_browser:
            parsed=re.fullmatch(r'\s*([a-zA-Z]+)(?:\((\d+|max)(?:\s*,\s*(\d+))?\))?\s*',declared)
            if parsed:
                actual=physical['data_type'].lower();expected=parsed[1].lower()
                aliases={'numeric':'decimal','integer':'int'}
                if aliases.get(actual,actual)!=aliases.get(expected,expected): issue('field_type_mismatch',table=table,column=source.get('fieldname'),**ref)
                elif parsed[2]:
                    mismatch=False
                    if expected in ['varchar','char','nvarchar','nchar','varbinary','binary']:
                        expected_length=-1 if parsed[2].lower()=='max' else int(parsed[2])*(2 if expected in ['nvarchar','nchar'] else 1)
                        mismatch=expected_length!=physical['max_length']
                    elif expected in ['decimal','numeric']:
                        mismatch=int(parsed[2])!=physical['precision'] or int(parsed[3] or 0)!=physical['scale']
                    elif expected in ['time','datetime2','datetimeoffset']:
                        mismatch=int(parsed[2])!=physical['scale']
                    if mismatch:issue('field_size_mismatch',table=table,column=source.get('fieldname'),declared=declared,actual=physical_sql_type(physical),**ref)
            else:issue('declared_type_unparsed',table=table,column=source.get('fieldname'),**ref)
        browser=browsers.get(source.get('type')) if source.get('fieldhtmltype')=='3' else None
        if source.get('fieldhtmltype')=='3' and not browser: issue('browser_definition_unresolved',browser_type=source.get('type'),**ref)
        key='/'.join(map(str,[form['form_source'],form['form_id'],table,group,field_id]))
        fields.append(dict(field_key=key,**ref,name=name,label_state=state,column_name=source.get('fieldname'),
            physical_table=table,group_id_raw=group,declared_db_type=declared,custom_browser_code=custom_browser,physical_column=physical,physical_sql_type=physical_sql_type(physical),
            html_type_raw=source.get('fieldhtmltype'),type_raw=source.get('type'),
            options=options.get((selector,field_id),[]),browser_definition=browser,configuration=source,
            source_ref=dict(object='dbo.workflow_billfield' if selector=='1' else 'dbo.workflow_formfield',id=field_id,form_id=form['form_id'])))

    def relation(form,parent,child,parent_column='id',child_column='mainid',group=None):
        parentcols=columns.get((parent or '').casefold(),{});childcols=columns.get((child or '').casefold(),{})
        found=parent_column.casefold() in parentcols and child_column.casefold() in childcols
        unique=((parent or '').casefold(),parent_column.casefold()) in unique_single
        if not found: issue('join_columns_not_found',form_id=form['form_id'],parent=parent,child=child)
        if not unique:issue('parent_unique_key_not_proven',form_id=form['form_id'],parent=parent,column=parent_column)
        foreign_groups=defaultdict(list)
        for row in tables.get('physical_foreign_keys',[]):
            foreign_groups[(row.get('child_schema','dbo'),row['child_table'],row['constraint_name'])].append(row)
        declared_fk=any(len(rows)==1 and rows[0].get('parent_schema','dbo')=='dbo'
            and rows[0].get('child_schema','dbo')=='dbo'
            and rows[0]['parent_table'].casefold()==(parent or '').casefold() and rows[0]['child_table'].casefold()==(child or '').casefold()
            and rows[0]['parent_column'].casefold()==parent_column.casefold() and rows[0]['child_column'].casefold()==child_column.casefold()
            and rows[0].get('is_disabled') is False and rows[0].get('is_not_trusted') is False for rows in foreign_groups.values())
        relationships.append(dict(form_source=form['form_source'],form_id=form['form_id'],parent_table=parent,parent_column=parent_column,
            child_table=child,child_column=child_column,group_id_filter_raw=group,
            cardinality='one_to_many_by_configuration',join_columns_present=found,
            parent_key_state='unique_single_column' if unique else 'not_proven_unique',
            database_fk_enforced=declared_fk,runtime_verified=False,
            basis='registered_detail_and_column_metadata' if group is None else 'old_form_group_configuration_and_column_metadata'))

    for (selector,form_id),ids in sorted(workflow_refs.items(),key=lambda x:(str(x[0][0]),str(x[0][1]))):
        source=bills.get(form_id) if selector=='1' else oldforms.get(form_id) if selector=='0' else None
        namespace='workflow_bill' if selector=='1' else 'workflow_formbase'
        if not source:
            issue('form_definition_missing',form_source=namespace,form_id=form_id,workflow_ids=ids);continue
        main=source.get('tablename') if selector=='1' else 'workflow_form'
        form=dict(form_source=namespace,form_id=form_id,workflow_ids=sorted(ids),main_table=main,
                  name=source.get('formname') or main,details=[],configuration=source)
        if selector=='1':
            form['name'],form['label_state']=label(labels.get(source.get('namelabel'),set()),main,dict(form_id=form_id,form_source=namespace))
            details=[r for r in tables.get('Workflow_billdetailtable',[]) if r['billid']==form_id]
            legacy=source.get('detailtablename')
            if legacy and legacy.casefold() not in {r['tablename'].casefold() for r in details}:
                issue('legacy_detail_table_not_registered',form_id=form_id,table=legacy)
            child_key=source.get('detailkeyfield') or 'mainid'
            for detail in sorted(details,key=lambda d:(d.get('orderid') or 0,d['id'])):
                table=detail['tablename']
                form['details'].append(dict(detail_id=detail['id'],table_name=table,title_raw=detail.get('title'),order_raw=detail.get('orderid')))
                relation(form,main,table,child_column=child_key)
                relationships[-1]['configured_detail_key_raw']=source.get('detailkeyfield')
            registered={d['table_name'].casefold() for d in form['details']}
            for field in sorted((f for f in billfields if f['billid']==form_id),key=lambda f:f['id']):
                detail=field.get('detailtable')
                if detail:
                    table=detail
                    if detail.casefold() not in registered:issue('detail_not_registered',form_id=form_id,field_id=field['id'],table=detail)
                elif field.get('viewtype')==0:table=main
                else:
                    table=None;issue('field_table_unresolved',form_id=form_id,field_id=field['id'],viewtype_raw=field.get('viewtype'))
                add_field(field,form,table,'1',field['id'],labels.get(field.get('fieldlabel'),set()))
        else:
            form['label_state']='form_definition_name'
            oldfields=[f for f in tables.get('workflow_formfield',[]) if f['formid']==form_id]
            groups=sorted({f.get('groupId') for f in oldfields if f.get('isdetail')=='1'},key=str)
            for group in groups:
                form['details'].append(dict(table_name='workflow_formdetail',group_id_raw=group,title_raw=None))
                relation(form,'workflow_form','workflow_formdetail','requestid','requestid',group)
            for binding in oldfields:
                isdetail=binding.get('isdetail')
                definition=(olddetail if isdetail=='1' else oldmain if isdetail=='0' else {}).get(binding['fieldid'])
                table='workflow_formdetail' if isdetail=='1' else 'workflow_form' if isdetail=='0' else None
                if isdetail is None and binding['fieldid'] in oldmain and binding['fieldid'] not in olddetail:
                    definition=oldmain[binding['fieldid']];table='workflow_form'
                    issue('old_null_detail_flag',form_id=form_id,field_id=binding['fieldid'],basis='only_main_dictionary_definition; compatible with local platform source')
                if definition is None:
                    issue('old_field_definition_unresolved',form_id=form_id,field_id=binding['fieldid'],isdetail_raw=isdetail)
                    definition=dict(id=binding['fieldid'],fieldname=None,fielddbtype=None,fieldhtmltype=None,type=None)
                add_field(definition,form,table,'0',binding['fieldid'],oldlabels.get((form_id,binding['fieldid']),set()),binding.get('groupId'))
                fields[-1]['binding']=binding
        if not columns.get((main or '').casefold()):issue('physical_main_table_not_found',form_id=form_id,table=main)
        forms.append(form)
    used={(f['physical_table'].casefold(),(f['column_name'] or '').casefold()) for f in fields if f['physical_table']}
    unmapped=[c for rows in columns.values() for name,c in rows.items() if (c['table_name'].casefold(),name) not in used]
    return dict(category=CATEGORY,normalization_version=NORMALIZATION_VERSION,semantic_state='partial_pending_confirmation',
        forms=forms,fields=fields,relationships=relationships,physical_columns_without_field_mapping=unmapped,issues=issues,
        custom_browser_references=[dict(code=code,field_keys=[f['field_key'] for f in fields if f['custom_browser_code']==code]) for code in sorted({f['custom_browser_code'] for f in fields if f['custom_browser_code']})],
        aggregation_rules=[
            '主表一行与明细多行分开建模；连接后主表金额不能按展开行直接求和。',
            '同一主表的多张明细先分别汇总到主表键，再关联；不能直接连接后交叉累计。',
            '配置和结构只能说明预期关系；唯一性、孤立行和实际行粒度未用业务记录验证。'],
        summary=dict(form_count=len(forms),field_count=len(fields),detail_group_count=sum(len(f['details']) for f in forms),
                     relationship_count=len(relationships),physical_table_count=len(columns),
                     issue_counts=dict(Counter(i['kind'] for i in issues))))
