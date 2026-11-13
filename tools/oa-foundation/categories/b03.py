"""B03 static topology and independent-rule evidence. No SQL evaluation."""
import re
from collections import Counter,defaultdict,deque

CATEGORY='B03'
NORMALIZATION_VERSION='1.0.0'
TYPE_NAMES={'0':'创建','1':'审批','2':'提交','3':'归档','4':'传阅','5':'等待','6':'自动处理'}

def graph_info(nodes,edges,starts):
    graph=defaultdict(list);incoming=Counter()
    for a,b in edges:
        if a in nodes and b in nodes:graph[a].append(b);incoming[b]+=1
    reachable=set(starts);queue=deque(starts)
    while queue:
        for other in graph[queue.popleft()]:
            if other not in reachable:reachable.add(other);queue.append(other)
    color={n:0 for n in nodes};cycle=False
    for node in sorted(nodes):
        if color[node]:continue
        color[node]=1;stack=[(node,iter(graph[node]))]
        while stack:
            here,children=stack[-1]
            try:
                other=next(children)
                if color[other]==1:cycle=True
                elif color[other]==0:color[other]=1;stack.append((other,iter(graph[other])))
            except StopIteration:color[here]=2;stack.pop()
    return dict(has_cycle=cycle,entry_candidates=sorted(starts),unreachable_from_entry=sorted(nodes-reachable),
                reachability_ignores_conditions=True,runtime_verified=False)

def normalize(tables,seed):
    issues=[];flows=[]
    def issue(kind,**refs):issues.append(dict(kind=kind,**refs))
    def index(name):
        result={}
        for row in tables.get(name,[]):
            if row['id'] in result:raise ValueError('Duplicate source key: '+name)
            result[row['id']]=row
        return result
    bases=index('workflow_nodebase');rules=index('rule_base');terms=index('rule_expressionbase');expressions=index('rule_expressions')
    index('workflow_nodelink');index('rule_maplist')
    bindings=set()
    for row in tables['workflow_flownode']:
        key=(row['workflowid'],row['nodeid'])
        if key in bindings:raise ValueError('Duplicate workflow/node binding')
        bindings.add(key)
    field_list=seed.get('B02',{}).get('fields',[])
    def resolve_field(raw,workflow):
        text=str(raw or '');match=re.fullmatch(r'(?:field)?(-?\d+)',text)
        candidates=[f for f in field_list if f['form_id']==workflow['form_id'] and f['form_source']==workflow['form_source'] and
                    ((f['field_id']==int(match[1])) if match else ((f.get('column_name') or '').casefold()==text.casefold()))]
        if len(candidates)==1:
            f=candidates[0];return dict(form_id=f['form_id'],form_source=f['form_source'],field_id=f['field_id'],name=f['name'],physical_table=f['physical_table'],column_name=f['column_name'])
        return None
    for workflow in seed['workflows']:
        wid=workflow['id'];nodes=[];routes=[]
        for binding in sorted((r for r in tables['workflow_flownode'] if r['workflowid']==wid),key=lambda r:r['nodeid']):
            base=bases.get(binding['nodeid'])
            if not base:issue('node_definition_missing_or_excluded',workflow_id=wid,node_id=binding['nodeid'])
            kind=binding['nodetype']
            if kind not in TYPE_NAMES:issue('unknown_node_type',workflow_id=wid,node_id=binding['nodeid'],raw=kind)
            nodes.append(dict(id=binding['nodeid'],name=base.get('nodename') if base else None,type_raw=kind,
                type_name_reference=TYPE_NAMES.get(kind,'未知'),configuration=binding,base_configuration=base,
                source_refs=[dict(object='dbo.workflow_flownode',workflowid=wid,nodeid=binding['nodeid']),dict(object='dbo.workflow_nodebase',id=binding['nodeid'])]))
        node_ids={n['id'] for n in nodes}
        for link in sorted((r for r in tables['workflow_nodelink'] if r['workflowid']==wid),key=lambda r:r['id']):
            if link['nodeid'] not in node_ids or link['destnodeid'] not in node_ids:
                issue('route_endpoint_missing',workflow_id=wid,route_id=link['id'],source_node=link['nodeid'],target_node=link['destnodeid'])
            route_rules=[];scope_candidates=[];had_path_mapping=False
            for mapping in tables.get('rule_maplist',[]):
                if mapping['linkid']!=link['id'] or mapping['rulesrc'] not in [1,-1]:continue
                scope_conflict=mapping.get('wfid') not in [wid,0,None]
                if scope_conflict:
                    issue('mapping_workflow_scope_conflict',workflow_id=wid,route_id=link['id'],mapping_id=mapping['id'],mapping_workflow=mapping.get('wfid'))
                if mapping.get('wfid') in [0,None]:issue('legacy_global_rule_mapping',workflow_id=wid,route_id=link['id'],mapping_id=mapping['id'])
                had_path_mapping=True
                rule=rules.get(mapping['ruleid'])
                if not rule:
                    issue('rule_definition_missing',workflow_id=wid,route_id=link['id'],rule_id=mapping['ruleid'])
                    scope_candidates.append(dict(rule_id=mapping['ruleid'],name=None,condition_sql_raw=None,rule_source_raw=None,
                        mapping=mapping,definition_state='missing',workflow_scope_state='mismatch_pending' if scope_conflict else 'definition_missing',
                        terms=[],expression_tree=[],parameter_mappings=[],evaluation_state='not_evaluated'))
                    continue
                if rule.get('formid') not in [None,workflow['form_id']]:issue('rule_form_scope_differs',workflow_id=wid,route_id=link['id'],rule_id=rule['id'],form_id_raw=rule.get('formid'))
                rule_context=dict(form_id=rule.get('formid'),form_source={1:'workflow_bill',0:'workflow_formbase'}.get(rule.get('isbill')))
                if rule_context['form_source']!=workflow['form_source']:
                    issue('rule_form_namespace_differs',workflow_id=wid,rule_id=rule['id'],isbill_raw=rule.get('isbill'))
                leafs=[]
                for term in sorted((r for r in terms.values() if r['ruleid']==rule['id']),key=lambda r:r['id']):
                    field=resolve_field(term.get('datafield'),rule_context)
                    if term.get('datafield') and field is None:issue('expression_field_reference_unresolved',workflow_id=wid,rule_id=rule['id'],expression_base_id=term['id'],raw=term.get('datafield'))
                    leafs.append(dict(id=term['id'],configuration=term,field_reference=field))
                tree=[];edges=[];owned={r['id']:r for r in expressions.values() if r['ruleid']==rule['id']}
                for item in sorted(owned.values(),key=lambda r:r['id']):
                    raw_children=item.get('expids') or ''
                    if isinstance(raw_children,str) and re.fullmatch(r'\s*\d+(?:\s*,\s*\d+)*\s*',raw_children):
                        children=[int(x.strip()) for x in raw_children.split(',')]
                    elif not raw_children:children=[]
                    else:
                        children=[];issue('expression_children_unparsed',workflow_id=wid,rule_id=rule['id'],expression_id=item['id'])
                    for child in children:
                        if child not in owned:issue('expression_child_reference_unresolved',workflow_id=wid,rule_id=rule['id'],expression_id=item['id'],child_id=child)
                        else:edges.append((item['id'],child))
                    leaf_id=item.get('expbaseid')
                    if leaf_id and leaf_id>0 and not any(t['id']==leaf_id for t in leafs):issue('expression_leaf_missing',workflow_id=wid,rule_id=rule['id'],expression_id=item['id'],leaf_id=leaf_id)
                    tree.append(dict(id=item['id'],children=children,configuration=item))
                if graph_info(set(owned),edges,set())['has_cycle']:issue('expression_cycle',workflow_id=wid,route_id=link['id'],rule_id=rule['id'])
                parameters=[r for r in tables.get('rule_mapitem',[]) if r['linkid']==link['id'] and r['ruleid']==rule['id'] and r['rulesrc']==mapping['rulesrc'] and r.get('rowidenty')==mapping.get('rowidenty')]
                (scope_candidates if scope_conflict else route_rules).append(dict(definition_state='present',workflow_scope_state='mismatch_pending' if scope_conflict else 'matched_or_legacy_global',rule_id=rule['id'],name=rule.get('rulename'),condition_sql_raw=rule.get('condit'),
                    rule_source_raw=rule.get('rulesrc'),mapping=mapping,terms=leafs,expression_tree=tree,
                    parameter_mappings=[dict(configuration=r,field_reference=resolve_field(r.get('formfieldid'),workflow)) for r in parameters],
                    evaluation_state='not_evaluated; activation and combination codes retained'))
            legacy=link.get('condition') or '';newrule=link.get('newrule') or ''
            condition_state='independent_rules_present' if route_rules else 'independent_rule_candidates_scope_unconfirmed' if any(c['definition_state']=='present' for c in scope_candidates) else 'rule_reference_unresolved' if had_path_mapping else 'legacy_condition_present' if legacy else 'newrule_reference_unresolved' if newrule else 'no_condition_definition_observed'
            routes.append(dict(id=link['id'],from_node=link['nodeid'],to_node=link['destnodeid'],name=link.get('linkname'),
                condition_state=condition_state,condition_sql_raw=legacy,
                condition_text_raw=link.get('newconditioncn') or link.get('conditioncn') or '',
                rule_combination_raw=link.get('ruleRelationship'),rules=route_rules,unresolved_rule_candidates=scope_candidates,configuration=link,
                source_ref=dict(object='dbo.workflow_nodelink',id=link['id']),runtime_verified=False))
        starts={n['id'] for n in nodes if n['type_raw']=='0' or (n['base_configuration'] or {}).get('isstart')=='1'}
        topology=graph_info(node_ids,[(r['from_node'],r['to_node']) for r in routes],starts)
        if not nodes:issue('no_static_nodes_observed',workflow_id=wid)
        elif not starts:issue('entry_node_not_identified',workflow_id=wid)
        for node_id in topology['unreachable_from_entry']:issue('node_not_topologically_reachable',workflow_id=wid,node_id=node_id)
        flows.append(dict(id=wid,name=workflow['name'],form_id=workflow['form_id'],nodes=nodes,routes=routes,topology=topology))
    return dict(category=CATEGORY,normalization_version=NORMALIZATION_VERSION,semantic_state='partial_pending_confirmation',
        runtime_verified=False,workflows=flows,issues=issues,
        limitations=['仅静态配置；排除实例专用节点与连线。','拓扑可达忽略条件、启停和运行期脚本，不表示实际请求路径。',
                     '条件SQL仅保留文本；规则启停与组合码保留原值，不执行求值。','节点中文类型来自既有本地E9参考档案，未知编码不推定。'],
        summary=dict(workflow_count=len(flows),node_count=sum(len(f['nodes']) for f in flows),route_count=sum(len(f['routes']) for f in flows),
                     mapped_rule_instances=sum(len(r['rules']) for f in flows for r in f['routes']),
                     unresolved_rule_candidate_count=sum(len(r['unresolved_rule_candidates']) for f in flows for r in f['routes']),
                     issue_counts=dict(Counter(i['kind'] for i in issues))))
