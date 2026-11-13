"""B04 static operator responsibility and base field permissions."""
import re
from collections import defaultdict,Counter
CATEGORY='B04'
NORMALIZATION_VERSION='1.0.0'
TYPES={1:'department',2:'role',3:'person',4:'everyone_dynamic',5:'form_field',6:'form_field_manager_dynamic',17:'creator_dynamic',18:'creator_manager_dynamic',40:'selected_node_operator_dynamic'}
PLATFORM_FIELDS={-1:('流程标题','requestname'),-2:('紧急程度','requestlevel'),-3:('短信提醒','messageType'),-4:('签字意见','remark'),-5:('微信提醒','chatsType'),-9:('打印次数','print_count')}
SIGNS={'0':'非会签','1':'会签','2':'依次逐个签','3':'抄送不需提交','4':'抄送需提交'}
MEMBER_TYPES={1:'person',2:'subcompany',3:'department',5:'jobtitle',8:'system_administrator_not_expanded'}

def flag(raw):
    return True if raw=='1' else False if raw=='0' else None

def int_ref(raw):
    value=str(raw).strip()
    return int(value) if re.fullmatch(r'-?\d+',value) else None

def normalize(tables,seed):
    issues=[];flows=[]
    def issue(kind,**refs):issues.append(dict(kind=kind,**refs))
    def index(name):
        result={}
        for row in tables.get(name,[]):
            if row['id'] in result:raise ValueError('Duplicate definition key: '+name)
            result[row['id']]=row
        return result
    roles=index('HrmRoles');people=index('HrmResource');departments=index('HrmDepartment');companies=index('HrmSubCompany');jobs=index('HrmJobTitles')
    bases=index('rule_base')
    fields=defaultdict(list);form_fields=defaultdict(set)
    for field in seed.get('B02',{}).get('fields',[]):
        key=(field['form_source'],field['form_id'],field['field_id']);fields[key].append(field)
        form_fields[key[:2]].add(field['field_id'])
    forms={(f['form_source'],f['form_id']):f for f in seed.get('B02',{}).get('forms',[])}
    def field_ref(value,context):
        match=re.fullmatch(r'(?:field)?(-?\d+)',str(value)) if value is not None else None
        if not match:return None
        choices=fields.get((context.get('form_source'),context.get('form_id'),int(match[1])),[])
        if len(choices)!=1:return None
        f=choices[0]
        return dict(form_source=f['form_source'],form_id=f['form_id'],field_id=f['field_id'],name=f['name'],column_name=f['column_name'],physical_table=f['physical_table'])
    members_by_role=defaultdict(list)
    for member in tables.get('HrmRoleMembers',[]):members_by_role[member['roleid']].append(member)
    groups_by_node=defaultdict(list)
    for group in tables['workflow_nodegroup']:groups_by_node[group['nodeid']].append(group)
    operators_by_group=defaultdict(list)
    for rule in tables['workflow_groupdetail']:operators_by_group[rule['groupid']].append(rule)
    objects_by_rule=defaultdict(list)
    known_rules={r['id'] for r in tables['workflow_groupdetail']}
    for row in tables.get('workflow_hrmoperator',[]):
        rule_id=int_ref(row.get('groupdetailid'))
        if rule_id not in known_rules:raise ValueError('Unassociated operator object')
        objects_by_rule[rule_id].append(row)
    permissions_by_node=defaultdict(list);permission_counts=Counter()
    for row in tables['workflow_nodeform']:
        permissions_by_node[row['nodeid']].append(row);permission_counts[(row['nodeid'],row['fieldid'])]+=1
    details_by_node=defaultdict(list)
    for row in tables.get('workflow_NodeFormGroup',[]):details_by_node[row['nodeid']].append(row)
    maps_by_operator=defaultdict(list)
    for row in tables.get('rule_maplist',[]):
        if row['rulesrc'] in [2,-2]:maps_by_operator[row['linkid']].append(row)
    terms_by_rule=defaultdict(list);trees_by_rule=defaultdict(list);params_by_rule=defaultdict(list)
    for row in tables.get('rule_expressionbase',[]):terms_by_rule[row['ruleid']].append(row)
    for row in tables.get('rule_expressions',[]):trees_by_rule[row['ruleid']].append(row)
    for row in tables.get('rule_mapitem',[]):params_by_rule[row['ruleid']].append(row)
    b03={f['id']:f for f in seed.get('B03',{}).get('workflows',[])}
    expected_nodes={(flow['id'],node['id']) for flow in b03.values() for node in flow['nodes']}
    observed_nodes={(r['workflowid'],r['nodeid']) for r in tables.get('workflow_flownode',[])}
    if observed_nodes!=expected_nodes:raise ValueError('Static node scope changed; refresh B03')
    known_nodes={node for _,node in expected_nodes}
    for source in ['workflow_nodegroup','workflow_nodeform','workflow_NodeFormGroup']:
        if any(row['nodeid'] not in known_nodes for row in tables.get(source,[])):raise ValueError('Unassociated node configuration: '+source)
    known_groups={g['id'] for g in tables['workflow_nodegroup']}
    if any(row['groupid'] not in known_groups for row in tables['workflow_groupdetail']):raise ValueError('Unassociated operator group')
    def member_model(row):
        code=row['resourcetype'];kind=MEMBER_TYPES.get(code,'unknown')
        data={1:people,2:companies,3:departments,5:jobs}.get(code,{}).get(row['resourceid'])
        name=None
        if data:name=data.get('lastname') or data.get('subcompanyname') or data.get('departmentname') or data.get('jobtitlename') or data.get('jobtitlemark')
        return dict(target_kind=kind,target_id=row['resourceid'],target_name=name,configuration=row,actual_operator=False)
    for workflow in seed['workflows']:
        wid=workflow['id'];nodes=[]
        for node in b03.get(wid,{}).get('nodes',[]):
            nid=node['id'];groups=[]
            for group in groups_by_node[nid]:
                operator_rules=[]
                for rule in sorted(operators_by_group[group['id']],key=lambda r:r['id']):
                    code=rule['type'];kind=TYPES.get(code,'unknown')
                    if kind=='unknown':issue('unknown_operator_type',workflow_id=wid,node_id=nid,rule_id=rule['id'],raw=code)
                    ref=None;role_members=[];references=[];objects=[]
                    for obj in objects_by_rule[rule['id']]:
                        gid=int_ref(obj.get('groupid'));matches=gid in [None,0,group['id']] and (gid is not None or obj.get('groupid') in [None,''])
                        object_ref=None
                        if not matches:issue('operator_object_group_conflict',workflow_id=wid,node_id=nid,rule_id=rule['id'],groupid_raw=obj.get('groupid'))
                        elif kind=='person':
                            person=people.get(int_ref(obj.get('objid')))
                            if person:
                                object_ref=dict(id=person['id'],name=person['lastname'],configuration=person)
                                references.append(object_ref)
                            else:issue('operator_object_person_unresolved',workflow_id=wid,node_id=nid,rule_id=rule['id'],objid_raw=obj.get('objid'))
                        objects.append(dict(configuration=obj,group_scope_state='matched_or_legacy' if matches else 'conflict_pending',target_reference=object_ref,actual_operator=False))
                    if kind=='role':
                        target=roles.get(rule['objid'])
                        if target:ref=dict(id=target['id'],name=target.get('rolesname') or target.get('rolesmark'),configuration=target)
                        role_members=[member_model(m) for m in members_by_role[rule['objid']]]
                    elif kind=='person':
                        target=people.get(rule['objid'])
                        if target:ref=dict(id=target['id'],name=target['lastname'],configuration=target)
                    elif kind=='department':
                        target=departments.get(rule['objid'])
                        if target:ref=dict(id=target['id'],name=target['departmentname'],configuration=target)
                    elif kind in ['form_field','form_field_manager_dynamic']:ref=field_ref(rule['objid'],workflow)
                    elif kind=='selected_node_operator_dynamic':
                        target=next((n for n in b03.get(wid,{}).get('nodes',[]) if n['id']==rule['objid']),None)
                        if target:ref=dict(node_id=target['id'],name=target['name'],actual_operators_not_read=True)
                    if kind=='person':
                        if ref:references.insert(0,ref)
                        references=list({x['id']:x for x in references}.values())
                        if ref is None and len(references)==1:ref=references[0]
                    elif ref:references=[ref]
                    if kind in ['department','role','person','form_field','form_field_manager_dynamic','selected_node_operator_dynamic'] and not references:
                        issue('operator_target_reference_unresolved',workflow_id=wid,node_id=nid,rule_id=rule['id'],type_raw=code,objid=rule['objid'])
                    sign=rule.get('signorder')
                    if sign not in SIGNS:issue('unknown_signorder',workflow_id=wid,node_id=nid,rule_id=rule['id'],raw=sign)
                    conditions=[]
                    for mapping in maps_by_operator[rule['id']]:
                        rb=bases.get(mapping['ruleid']);scope_conflict=mapping.get('wfid') not in [wid,0,None]
                        if scope_conflict:issue('operator_rule_workflow_scope_conflict',workflow_id=wid,node_id=nid,operator_rule_id=rule['id'],mapping_id=mapping['id'])
                        if rb is None:
                            issue('operator_condition_definition_missing',workflow_id=wid,node_id=nid,operator_rule_id=rule['id'],rule_id=mapping['ruleid'])
                            conditions.append(dict(mapping=mapping,definition_state='missing',configuration=None,terms=[],expression_tree=[],parameter_mappings=[]));continue
                        context=dict(form_id=rb.get('formid'),form_source={1:'workflow_bill',0:'workflow_formbase'}.get(rb.get('isbill')))
                        leafs=[]
                        for term in terms_by_rule[rb['id']]:
                            fr=field_ref(term.get('datafield'),context)
                            if term.get('datafield') and fr is None:issue('operator_condition_field_unresolved',workflow_id=wid,node_id=nid,rule_id=rb['id'],term_id=term['id'])
                            leafs.append(dict(configuration=term,field_reference=fr))
                        params=[dict(configuration=p,field_reference=field_ref(p.get('formfieldid'),workflow)) for p in params_by_rule[rb['id']] if p['linkid']==rule['id'] and p['rulesrc']==mapping['rulesrc'] and p.get('rowidenty')==mapping.get('rowidenty')]
                        conditions.append(dict(mapping=mapping,definition_state='present',workflow_scope_state='mismatch_pending' if scope_conflict else 'matched_or_legacy_global',
                            configuration=rb,terms=leafs,expression_tree=trees_by_rule[rb['id']],parameter_mappings=params,evaluation_state='not_evaluated'))
                    operator_rules.append(dict(id=rule['id'],operator_type_raw=code,target_kind=kind,target_reference=ref,
                        target_references=references,configured_objects=objects,role_members=role_members,signorder_raw=sign,signorder_reference=SIGNS.get(sign,'未知'),signtype_raw=rule.get('signtype'),
                        order_batch_raw=rule.get('orders'),configuration=rule,
                        legacy_condition_sql_raw=rule.get('CONDITIONS'),legacy_condition_text_raw=rule.get('CONDITIONCN'),independent_conditions=conditions,
                        runtime_dependency=kind.endswith('_dynamic') or kind in ['form_field','role','department'],actual_operators_resolved=False))
                if not operator_rules:issue('operator_group_without_rules',workflow_id=wid,node_id=nid,group_id=group['id'])
                groups.append(dict(id=group['id'],name=group.get('groupname'),configuration=group,operator_rules=operator_rules))
            permission_rows=[];seen=set()
            for row in permissions_by_node[nid]:
                field=field_ref(row['fieldid'],workflow)
                if row['fieldid'] in PLATFORM_FIELDS:
                    name,technical_name=PLATFORM_FIELDS[row['fieldid']]
                    field=dict(namespace='platform',field_id=row['fieldid'],name=name,technical_name_reference=technical_name,semantics_basis='local_source_reference_not_deployed_runtime',physical_table=None,column_name=None)
                seen.add(row['fieldid']);ambiguous=permission_counts[(nid,row['fieldid'])]>1
                if ambiguous:issue('duplicate_field_permission',workflow_id=wid,node_id=nid,field_id=row['fieldid'])
                if field is None:issue('permission_field_unresolved',workflow_id=wid,node_id=nid,field_id=row['fieldid'])
                visible,editable,mandatory=(None,None,None) if ambiguous else (flag(row.get('isview')),flag(row.get('isedit')),flag(row.get('ismandatory')))
                if mandatory is True and editable is False:issue('required_without_base_edit_permission',workflow_id=wid,node_id=nid,field_id=row['fieldid'])
                permission_rows.append(dict(field_id=row['fieldid'],field_reference=field,visible_base=visible,editable_base=editable,mandatory_base=mandatory,
                    permission_record_state='ambiguous' if ambiguous else 'present',configuration=row,effective_ui_permission_verified=False))
            missing=sorted(form_fields[(workflow['form_source'],workflow['form_id'])]-seen)
            if missing:issue('permission_records_missing',workflow_id=wid,node_id=nid,field_count=len(missing))
            detail_permissions=[];form=forms.get((workflow['form_source'],workflow['form_id']),{});detail_defs=form.get('details',[])
            ordered=sorted(detail_defs,key=lambda d:(d.get('order_raw') or 0,str(d.get('detail_id'))))
            order_values=[d.get('order_raw') for d in ordered]
            deterministic=len(order_values)==len(set(order_values)) and None not in order_values
            for row in details_by_node[nid]:
                detail=None
                if workflow['form_source']=='workflow_bill' and deterministic and type(row['groupid']) is int and 0<=row['groupid']<len(ordered):
                    detail=ordered[row['groupid']]
                elif workflow['form_source']=='workflow_formbase':
                    matches=[d for d in detail_defs if d.get('group_id_raw')==row['groupid']]
                    if len(matches)==1:detail=matches[0]
                if detail is None:issue('detail_permission_group_unresolved',workflow_id=wid,node_id=nid,group_id=row['groupid'])
                detail_permissions.append(dict(group_id_raw=row['groupid'],detail_reference=detail,mapping_basis='local_source_zero_based_order_reference' if detail and workflow['form_source']=='workflow_bill' else 'old_group_or_unresolved',
                    configuration=row,effective_ui_permission_verified=False))
            nodes.append(dict(id=nid,name=node['name'],type_raw=node.get('type_raw'),groups=groups,permissions=permission_rows,
                missing_permission_field_ids=missing,missing_permission_meaning='unknown_not_denied',detail_permissions=detail_permissions))
        flows.append(dict(id=wid,name=workflow['name'],form_id=workflow['form_id'],form_source=workflow['form_source'],nodes=nodes))
    return dict(category=CATEGORY,normalization_version=NORMALIZATION_VERSION,semantic_state='partial_pending_confirmation',actual_operators_resolved=False,
        workflows=flows,issues=issues,organization_definitions=dict(roles=list(roles.values()),role_members=tables.get('HrmRoleMembers',[]),
            people=list(people.values()),departments=list(departments.values()),subcompanies=list(companies.values()),jobtitles=list(jobs.values())),
        limitations=['角色成员是配置候选，尚未按单据、部门、级别、条件或代理解析实际办理人。',
                     '基础字段权限与缺记录/空标志分开；布局、联动和脚本可能改变最终页面行为。','只读最小必要组织与人员引用，不读取业务单据或当前待办。'],
        summary=dict(workflow_count=len(flows),node_count=sum(len(f['nodes']) for f in flows),
            operator_group_count=len(tables['workflow_nodegroup']),operator_rule_count=len(tables['workflow_groupdetail']),operator_object_count=len(tables.get('workflow_hrmoperator',[])),
            permission_record_count=len(tables['workflow_nodeform']),detail_permission_count=len(tables.get('workflow_NodeFormGroup',[])),
            role_count=len(roles),referenced_person_count=len(people),role_member_definition_count=len(tables.get('HrmRoleMembers',[])),
            issue_counts=dict(Counter(i['kind'] for i in issues))))
