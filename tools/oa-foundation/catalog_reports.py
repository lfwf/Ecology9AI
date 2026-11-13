"""Offline human-readable catalogs. Source text is escaped, never executed."""
import csv,html,json
from datetime import datetime,timezone,timedelta
from collections import Counter,defaultdict

def cell(value):return html.escape('' if value is None else str(value),quote=True)
def table(headers,rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+cell(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+cell(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def csv_file(path,headers,rows):
    def safe(v):return "'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\n','\r')) else v
    with path.open('x',encoding='utf-8-sig',newline='') as s:
        writer=csv.writer(s);writer.writerow(headers);writer.writerows([[safe(v) for v in row] for row in rows])
def report(path,raw,doc,diff):
    if doc['category']=='B03':return report_b03(path,raw,doc,diff)
    if doc['category']=='B04':return report_b04(path,raw,doc,diff)
    if doc['category']=='B05':return report_b05(path,raw,doc,diff)
    if doc['category']=='B06':return report_b06(path,raw,doc,diff)
    if doc['category']=='B07':return report_b07(path,raw,doc,diff)
    if doc['category']=='B08':return report_b08(path,raw,doc,diff)
    if doc['category']=='B09':
        from runtime_report import report_b09
        return report_b09(path,raw,doc,diff)
    if doc['category']!='B02':raise ValueError('Report category not yet registered')
    summary=doc['summary']
    body='<h1>B02 表单字段与主明细关系 · 待审核</h1>'
    body+='<p>采集时间：'+cell(datetime.fromisoformat(raw['started_at']).astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds'))+' 至 '+cell(datetime.fromisoformat(raw['ended_at']).astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds'))+'。本次只读配置和系统结构，业务单据读取为0。</p>'
    body+='<p>表单'+str(summary['form_count'])+'个，字段'+str(summary['field_count'])+'个，登记明细'+str(summary['detail_group_count'])+'组，物理对象'+str(summary['physical_table_count'])+'个。表单和流程版本分开保留。</p>'
    body+='<h2>怎样理解这些关系</h2><ul>'+''.join('<li>'+cell(x)+'</li>' for x in doc['aggregation_rules'])+'</ul>'
    body+='<p>配置前后两遍内容一致，但不代表事务级同一时点快照。唯一键、外键按数据库元数据注明；未用实际单据验证重复键、孤立行、真实行数或办理结果。</p>'
    formrows=[]
    grouped=defaultdict(list)
    for field in doc['fields']:grouped[(field['form_source'],field['form_id'])].append(field)
    for form in doc['forms']:
        details='；'.join(str(d['table_name'])+'（顺序/组 '+str(d.get('order_raw',d.get('group_id_raw')))+'）' for d in form['details'])
        formrows.append([form['name'],form['form_id'],','.join(map(str,form['workflow_ids'])),form['main_table'],details,len(grouped[(form['form_source'],form['form_id'])])])
    body+='<h2>表单与表目录</h2>'+table(['表单名称','表单原ID','引用流程编号','主表','明细表','字段数'],formrows)
    fieldheaders=['表单','字段名称','数据库列','所属表','配置类型原值','实际列类型','控件类型原值','浏览框代码','选项（编码=名称，含原始停用项）']
    fieldrows=[]
    for form in doc['forms']:
        rows=[]
        for field in grouped[(form['form_source'],form['form_id'])]:
            physical=field['physical_column'] or {}
            rows.append([form['name'],field['name'],field['column_name'],field['physical_table'],field['declared_db_type'],
                field['physical_sql_type'],field['html_type_raw'],field['custom_browser_code'] or (field['type_raw'] if field['html_type_raw']=='3' else ''),'；'.join(str(o['selectvalue'])+'='+str(o['selectname']) for o in field['options'])])
        fieldrows.extend(rows)
        body+='<details><summary>'+cell(form['name'])+' · 表单'+cell(form['form_id'])+' · '+str(len(rows))+'字段</summary>'+table(fieldheaders,rows)+'</details>'
    relations=[[r['form_id'],r['parent_table'],r['parent_column'],r['child_table'],r['child_column'],r['parent_key_state'],r['database_fk_enforced'],False] for r in doc['relationships']]
    body+='<h2>主明细关联</h2>'+table(['表单ID','主表','主表键','明细表','明细关联列','主表唯一性依据','有可信数据库外键','已用业务行验证'],relations)
    issue_names=dict(custom_browser_definition_pending='自定义浏览框定义待追查',old_null_detail_flag='旧式表单空明细标志需保留依据',parent_unique_key_not_proven='主表单列唯一键尚无结构证明',field_type_mismatch='配置与物理列类型不同',field_size_mismatch='配置与物理列长度或精度不同',
        label_missing='中文标签未匹配',label_ambiguous='中文标签存在冲突',configured_column_not_found='字段未匹配到物理列',detail_not_registered='字段引用的明细未登记',field_table_unresolved='字段所属表未确定',old_field_definition_unresolved='旧式字段定义未确定',declared_type_unparsed='配置类型格式未解释')
    counts=Counter(i['kind'] for i in doc['issues'])
    body+='<h2>待核对事项</h2>'+table(['事项','数量'],[[issue_names.get(k,k),n] for k,n in sorted(counts.items())])
    for kind in sorted(counts):
        examples=[i for i in doc['issues'] if i['kind']==kind][:12]
        body+='<details><summary>'+cell(issue_names.get(kind,kind))+' · 示例</summary><pre>'+cell(json.dumps(examples,ensure_ascii=False,indent=2))+'</pre></details>'
    body+='<p>自定义浏览框仅保存引用代码，后续沿代码追查建模与数据来源；未执行浏览框SQL。配置/物理类型不同是待核对事实，尚未判断为配置错误。完整缺口在normalized.json。</p>'
    body+='<h2>本次变更</h2><p>'+cell({'baseline':'首批基线，不记为全部新增。','not_comparable':'方法、来源或结构口径变化，本批不直接作配置差异比较。','compared':'已比较同口径批次，逐来源变化见diff.json。'}[diff['status']])+'</p>'
    content='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>B02表单字段与关系</title><style>body{font:16px/1.7 system-ui;margin:30px;color:#18222b}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ccd3da;padding:7px;text-align:left;vertical-align:top}th{background:#edf2f6}.scroll{overflow:auto}details{margin:14px 0}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere}p{max-width:1100px}</style>'+body+'</html>'
    (path/'B02表单字段与关系.html').write_text(content,'utf-8')
    csv_file(path/'字段字典.csv',fieldheaders,fieldrows)
    csv_file(path/'主明细关系.csv',['表单ID','主表','主表键','明细表','明细关联列','唯一键状态','可信数据库外键','运行验证'],relations)

def report_b03(path,raw,doc,diff):
    states={'independent_rules_present':'有独立规则定义','legacy_condition_present':'有传统条件文本','newrule_reference_unresolved':'新规则引用待解释','rule_reference_unresolved':'存在规则引用，定义未匹配','independent_rule_candidates_scope_unconfirmed':'存在独立条件候选，流程归属待核对','no_condition_definition_observed':'未观察到条件定义，不能直接认定无条件'}
    local=lambda value:datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    body='<h1>B03 节点与流转规则 · 待审核</h1><p>采集时间：'+cell(local(raw['started_at']))+' 至 '+cell(local(raw['ended_at']))+'。</p>'
    body+='<p>流程定义'+str(doc['summary']['workflow_count'])+'条，静态节点'+str(doc['summary']['node_count'])+'个，连线'+str(doc['summary']['route_count'])+'条。业务单据读取0；没有执行条件SQL或规则求值。</p>'
    body+='<ul>'+''.join('<li>'+cell(x)+'</li>' for x in doc['limitations'])+'</ul>'
    node_rows=[];route_rows=[];rule_rows=[]
    for flow in doc['workflows']:
        names={n['id']:n['name'] for n in flow['nodes']}
        nr=[[flow['id'],flow['name'],n['id'],n['name'],n['type_raw'],n['type_name_reference']] for n in flow['nodes']]
        rr=[];rules=[]
        for route in flow['routes']:
            conditions=route['condition_text_raw'] or route['condition_sql_raw']
            rr.append([flow['id'],route['id'],route['from_node'],names.get(route['from_node']),route['to_node'],names.get(route['to_node']),route['name'],states[route['condition_state']],conditions,len(route['rules']),route['rule_combination_raw']])
            for rule in route['rules']+route['unresolved_rule_candidates']:
                mapping=rule['mapping']
                rules.append([flow['id'],route['id'],rule['rule_id'],rule['name'],rule['workflow_scope_state'],mapping.get('rulesrc'),rule['rule_source_raw'],mapping.get('isused'),mapping.get('nm'),mapping.get('rowidenty'),rule['condition_sql_raw'],len(rule['terms']),len(rule['parameter_mappings'])])
        node_rows.extend(nr);route_rows.extend(rr);rule_rows.extend(rules)
        topo=flow['topology']
        body+='<details><summary>'+cell(flow['name'])+' · 流程'+cell(flow['id'])+' · '+str(len(nr))+'节点/'+str(len(rr))+'连线</summary>'
        body+='<p>入口候选：'+cell(topo['entry_candidates'])+'；存在拓扑回路：'+cell(topo['has_cycle'])+'。回路可能用于退回或返工，本目录不据此判定配置错误。</p>'
        body+=table(['流程ID','流程','节点ID','节点名称','类型原值','类型参考'],nr)
        body+=table(['流程ID','路径ID','来源节点ID','来源节点','目标节点ID','目标节点','路径','条件资料状态','条件说明原文','独立规则数','组合原值'],rr)
        if rules:body+='<details><summary>独立规则明细（仅文本与原值）</summary>'+table(['流程ID','路径ID','规则ID','规则名称','流程归属核对','映射来源码','规则定义来源码','使用原值','nm原值','行标记原值','条件SQL原文','表达式项数','参数映射数'],rules)+'</details>'
        body+='</details>'
    body+='<h2>待核对事项</h2>'+table(['事项代码','数量'],sorted(doc['summary']['issue_counts'].items()))
    body+='<p>完整问题、原始条件、表达式树、字段与参数映射见normalized.json。独立规则表和传统condition列分开保留；不同规则的组合与启停原值尚未统一解释，不能将列表顺序视为执行顺序。</p>'
    body+='<p>相对前批状态：'+cell(diff['status'])+'。条件和配置的逐来源变更见diff.json。任何可达性均未用实际单据验证。</p>'
    content='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>B03节点与流转规则</title><style>body{font:16px/1.7 system-ui;margin:30px;color:#18222b}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ccd3da;padding:7px;vertical-align:top;max-width:600px;overflow-wrap:anywhere}th{background:#edf2f6}.scroll{overflow:auto}details{margin:14px 0}summary{cursor:pointer;font-weight:600}</style>'+body+'</html>'
    (path/'B03节点与流转规则.html').write_text(content,'utf-8')
    csv_file(path/'节点目录.csv',['流程ID','流程','节点ID','节点名称','类型原值','类型参考'],node_rows)
    csv_file(path/'路径与条件.csv',['流程ID','路径ID','来源节点ID','来源节点','目标节点ID','目标节点','路径','条件资料状态','条件说明原文','独立规则数','组合原值'],route_rows)
    csv_file(path/'独立规则.csv',['流程ID','路径ID','规则ID','规则名称','流程归属核对','映射来源码','规则定义来源码','使用原值','nm原值','行标记原值','条件SQL原文','表达式项数','参数映射数'],rule_rows)

def report_b04(path,raw,doc,diff):
    local=lambda v:datetime.fromisoformat(v).astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    booltext=lambda v:'是' if v is True else '否' if v is False else '未知'
    kind_names={'department':'部门候选（动态）','everyone_dynamic':'所有人（动态）','form_field_manager_dynamic':'表单人员字段经理（动态）','role':'角色','person':'固定人员','form_field':'表单字段取人','creator_dynamic':'创建人本人（动态）','creator_manager_dynamic':'创建人经理（动态）','selected_node_operator_dynamic':'所选节点操作者（动态）','unknown':'未知类型'}
    s=doc['summary'];body='<h1>B04 审核人与字段权限 · 待审核</h1><p>采集时间：'+cell(local(raw['started_at']))+' 至 '+cell(local(raw['ended_at']))+'。只读取静态规则、基础权限及最少必要组织引用，业务单据读取0。</p>'
    body+='<ul>'+''.join('<li>'+cell(x)+'</li>' for x in doc['limitations'])+'</ul>'
    body+='<p>审核组'+str(s['operator_group_count'])+'个，取人规则'+str(s['operator_rule_count'])+'条，字段权限记录'+str(s['permission_record_count'])+'条，明细操作记录'+str(s['detail_permission_count'])+'条。角色候选成员不表示实际参与审批的人员。</p>'
    indexrows=[];all_permissions=[];all_operators=[];all_details=[];all_missing=[];all_objects=[]
    ph=['流程ID','节点ID','节点','字段ID','字段名称','物理表','数据库列','基础可见','基础可编辑','基础必填','禁止手改原值','记录状态']
    oh=['流程ID','节点ID','节点','组','规则ID','取人类型原值','取人参考','静态目标/引用','会签抄送参考','signorder原值','signtype原值','批次原值','级别原值','条件说明原文','独立条件映射数']
    dh=['流程ID','节点ID','节点','明细组原值','明细表参考','允许新增原值','允许编辑原值','允许删除原值','允许复制原值','必需原值','默认行数原值']
    for flow in doc['workflows']:
        nr=[];pr=[];orr=[];dr=[];missing=[]
        for node in flow['nodes']:
            for group in node['groups']:
                for rule in group['operator_rules']:
                    for obj in rule.get('configured_objects',[]):
                        cfg=obj['configuration'];target=obj.get('target_reference') or {}
                        all_objects.append([flow['id'],node['id'],group['id'],rule['id'],cfg.get('type'),cfg.get('objid'),target.get('name'),cfg.get('groupid'),cfg.get('groupdetailid'),cfg.get('signorder'),cfg.get('orders'),obj['group_scope_state']])
                    ref=rule['target_reference'] or {}
                    name='、'.join(str(r.get('name') or r.get('field_id') or r.get('id')) for r in rule.get('target_references',[]) ) or ref.get('name') or ref.get('physical_table') or '待上下文解析'
                    orr.append([flow['id'],node['id'],node['name'],group['name'],rule['id'],rule['operator_type_raw'],kind_names[rule['target_kind']],name,
                        rule['signorder_reference'],rule['signorder_raw'],rule['signtype_raw'],rule['order_batch_raw'],rule['configuration'].get('level_n'),
                        rule['legacy_condition_text_raw'] or rule['legacy_condition_sql_raw'],len(rule['independent_conditions'])])
            for permission in node['permissions']:
                ref=permission['field_reference'] or {};cfg=permission['configuration']
                pr.append([flow['id'],node['id'],node['name'],permission['field_id'],ref.get('name') or '未匹配/平台字段',ref.get('physical_table'),ref.get('column_name'),
                    booltext(permission['visible_base']),booltext(permission['editable_base']),booltext(permission['mandatory_base']),cfg.get('isonlyshow'),permission['permission_record_state']])
            for fieldid in node['missing_permission_field_ids']:missing.append([flow['id'],node['id'],node['name'],fieldid,'未知，不能视为拒绝'])
            for detail in node['detail_permissions']:
                cfg=detail['configuration'];ref=detail['detail_reference'] or {}
                dr.append([flow['id'],node['id'],node['name'],detail['group_id_raw'],ref.get('table_name'),cfg.get('isadd'),cfg.get('isedit'),cfg.get('isdelete'),cfg.get('iscopy'),cfg.get('isneed'),cfg.get('defaultrows')])
            nr.append([node['id'],node['name'],len(node['groups']),sum(len(g['operator_rules']) for g in node['groups']),len(node['permissions']),len(node['missing_permission_field_ids']),len(node['detail_permissions'])])
        all_permissions.extend(pr);all_operators.extend(orr);all_details.extend(dr);all_missing.extend(missing)
        filename='B04流程_'+str(flow['id'])+'.html'
        flowbody='<h1>'+cell(flow['name'])+' · 流程'+cell(flow['id'])+'</h1><p><a href="B04审核人与字段权限.html">返回总目录</a>。基础权限不等于最终页面权限；缺少记录为未知，动态脚本和布局另见B05。</p>'
        flowbody+='<h2>节点概览</h2>'+table(['节点ID','节点','审核组数','规则数','字段记录数','缺记录字段数','明细组数'],nr)
        flowbody+='<h2>取人与会签规则</h2>'+table(oh,orr)
        flowbody+='<p>独立条件的SQL文本、表达式、参数映射和字段上下文见normalized.json；未执行或展开成实际办理人。</p>'
        flowbody+='<h2>明细操作基础配置</h2>'+table(dh,dr)
        flowbody+='<h2>字段基础权限矩阵</h2>'+table(ph,pr)
        if missing:flowbody+='<h2>缺少权限记录</h2>'+table(['流程ID','节点ID','节点','字段ID','解释'],missing)
        content='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+cell(flow['name'])+'责任与权限</title><style>body{font:16px/1.7 system-ui;margin:30px;color:#18222b}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ccd3da;padding:7px;vertical-align:top;max-width:600px;overflow-wrap:anywhere}th{background:#edf2f6}.scroll{overflow:auto}a{color:#175778}</style>'+flowbody+'</html>'
        (path/filename).write_text(content,'utf-8')
        indexrows.append([flow['id'],flow['name'],len(flow['nodes']),len(orr),len(pr),len(missing),filename])
    body+='<h2>按流程查看</h2><ul>'+''.join('<li><a href="'+cell(row[-1])+'">'+cell(row[1])+' · '+str(row[0])+'</a>：'+str(row[3])+'规则，'+str(row[4])+'字段记录，'+str(row[5])+'缺记录字段</li>' for row in indexrows)+'</ul>'
    body+='<h2>待核对事项</h2>'+table(['事项代码','数量'],sorted(s['issue_counts'].items()))
    body+='<p>基础只读且必填需结合默认值、联动或脚本核对，不直接判为错误。明细组映射采用本地源码排序序号参考，未验证线上部署。人员仅有id、姓名、状态及部门/分部/经理标识，没有密码、联系方式或业务办理记录。</p>'
    body+='<p>固定人员名单每行的独立会签、次序和原始类型见配置人员对象.csv；完整责任定义、角色成员对象类型和条件表达式保存在normalized.json；变更状态为'+cell(diff['status'])+'，逐来源差异见diff.json。</p>'
    content='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>B04审核人与字段权限</title><style>body{font:16px/1.7 system-ui;margin:30px;color:#18222b}table{border-collapse:collapse}td,th{border:1px solid #ccd3da;padding:7px}.scroll{overflow:auto}a{color:#175778}</style>'+body+'</html>'
    (path/'B04审核人与字段权限.html').write_text(content,'utf-8')
    csv_file(path/'配置人员对象.csv',['流程ID','节点ID','组ID','规则ID','名单类型原值','目标ID原值','人员名称参考','组原值','规则原值','会签抄送原值','次序原值','组关联状态'],all_objects)
    csv_file(path/'审核人规则.csv',oh,all_operators);csv_file(path/'字段权限矩阵.csv',ph,all_permissions)
    csv_file(path/'明细操作权限.csv',dh,all_details);csv_file(path/'缺少权限记录.csv',['流程ID','节点ID','节点','字段ID','解释'],all_missing)

def report_b05(path,raw,doc,diff):
    local=lambda v:datetime.fromisoformat(v).astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    names={'layouts':'布局','formulas':'公式','linkages':'属性联动','data_inputs':'数据带入','field_attributes':'字段默认/转换属性','actions':'附加操作','numbering':'编号规则','withdrawal':'撤回配置','function_permissions':'流转功能配置','overtime':'节点超时','link_reminders':'路径超时提醒'}
    style='<style>body{font:16px/1.7 system-ui;margin:28px;color:#18222b}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ccd3da;padding:7px;vertical-align:top;max-width:650px;overflow-wrap:anywhere}th{background:#edf2f6}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f7;padding:14px}a{color:#175778}</style>'
    def save(name,title,body):
        (path/name).write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+cell(title)+'</title>'+style+body+'</html>','utf-8')
    lh=['流程ID','节点ID','布局ID','名称','活动参考','设备类型原值','视图原值','布局解析','控件数','脚本源数']
    sh=['流程ID','节点ID','布局ID','通道','活动参考','解码','提交/保存等入口','网络引用数','写字段数','属性变化数','源哈希']
    ph=['流程ID','节点ID','布局ID','字段ID','名称','物理表','数据库列','表区','单元格','隐藏参考']
    ih=['流程ID','触发项ID','查询ID','映射ID','触发字段','目标字段','目标表','目标列','来源表','来源列','映射类型原值','条件原文','数据源名称']
    ah=['流程ID','类别','来源','节点/对象原值','字段参考','关联参考','配置原文（仅数据）']
    all_l=[];all_s=[];all_p=[];all_i=[];all_a=[];links=[]
    for flow in doc['workflows']:
        layouts=[];scripts=[];inputs=[];autos=[]
        for layout in flow['layouts']:
            cfg=layout['configuration'];active='活动参考' if layout['active_reference'] is True else '停用参考' if layout['active_reference'] is False else '未知'
            layouts.append([flow['id'],layout['node_id'],layout['id'],layout['name'],active,cfg.get('type'),cfg.get('viewtype'),layout['parse_status'],len(layout['placements']),len(layout['scripts'])])
            for placement in layout['placements']:
                cfgp=placement['configuration'];ref=placement['field_reference'] or {}
                all_p.append([flow['id'],layout['node_id'],layout['id'],cfgp['field_id'],ref.get('name'),ref.get('physical_table'),ref.get('column_name'),cfgp.get('table'),cfgp.get('cell'),','.join(cfgp.get('hidden',[]))])
            for script in layout['scripts']:
                a=script['analysis'];scripts.append([flow['id'],layout['node_id'],layout['id'],','.join(script['channels']),active,script['decoding']['status'],','.join(sorted({op for e in a['events'] for op in e['operations']})),len(a['network_calls']),len(script['field_writes']),len(script['attribute_changes']),script['decoding']['input_sha256']])
        for item in flow['data_inputs']:
            trigger=item['trigger_field_reference'] or {}
            for query in item['queries']:
                cfg=query['configuration']
                for mapping in query['mappings']:
                    target=mapping['target_field_reference'] or {};source=mapping['source_table_reference'] or {};mcfg=mapping['configuration']
                    inputs.append([flow['id'],item['id'],query['id'],mcfg.get('id'),trigger.get('name'),target.get('name'),target.get('physical_table'),target.get('column_name'),source.get('TableName'),mcfg.get('DBFieldName'),mapping['mapping_type_raw'],cfg.get('WhereClause'),cfg.get('datasourcename')])
        for kind in names:
            if kind in ['layouts','data_inputs']:continue
            for item in flow[kind]:
                cfg=item['configuration'];ref=item.get('field_reference') or item.get('destination_field_reference') or {}
                relation={k:item[k] for k in ['binding_kind','binding_reference','node_scope_state','parent_timeout_reference','rule_id_raw'] if k in item}
                if item.get('independent_condition'):relation['independent_condition']=dict(id=item['independent_condition']['id'],definition_state=item['independent_condition']['definition_state'])
                autos.append([flow['id'],names[kind],item.get('source',kind),cfg.get('nodeid',cfg.get('objid')),ref.get('name'),json.dumps(relation,ensure_ascii=False),json.dumps(cfg,ensure_ascii=False)])
        all_l.extend(layouts);all_s.extend(scripts);all_i.extend(inputs);all_a.extend(autos)
        body='<h1>'+cell(flow['name'])+' · 自动处理配置</h1><p><a href="B05自动处理配置.html">返回总目录</a>。仅整理定义；SQL、脚本和动作均未执行。</p>'
        body+='<h2>布局与脚本通道</h2>'+table(lh,layouts)+table(sh,scripts)
        body+='<h2>数据带入字段映射</h2>'+table(ih,inputs)
        # Include entries and queries with no mapping, so empty definitions remain reviewable.
        body+='<details><summary>完整带入定义、启用原值与无映射项</summary><pre>'+cell(json.dumps(flow['data_inputs'],ensure_ascii=False,indent=2))+'</pre></details>'
        body+='<h2>公式、联动、赋值与自动动作</h2>'+table(ah,autos)
        for layout in flow['layouts']:
            for script in layout['scripts']:
                body+='<details><summary>布局'+cell(layout['id'])+' / '+cell(','.join(script['channels']))+' · 脚本文本与静态线索</summary><p>已遮蔽明显的字面凭据，未执行。完整静态调用与字段上下文见normalized.json。</p><pre>'+cell(script['text'])+'</pre><pre>'+cell(json.dumps(script['analysis'],ensure_ascii=False,indent=2))+'</pre></details>'
        filename='B05流程_'+str(flow['id'])+'.html';save(filename,flow['name']+'自动配置',body)
        links.append('<li><a href="'+filename+'">'+cell(flow['name'])+' · '+str(flow['id'])+'</a>：'+str(len(layouts))+'布局，'+str(len(scripts))+'脚本源，'+str(len(autos))+'其他动作</li>')
    body='<h1>B05 自动处理配置 · 待审核</h1><p>配置采集时间：'+cell(local(raw['started_at']))+' 至 '+cell(local(raw['ended_at']))+'。业务单据读取0。</p>'
    body+='<ul>'+''.join('<li>'+cell(s)+'</li>' for s in doc['limitations'])+'</ul>'
    body+=table(['类别','配置数'],[(names[k],v) for k,v in doc['summary']['counts'].items()])
    issue_names={'automation_field_unresolved':'字段尚未匹配（包含停用布局）','action_node_scope_conflict':'附加操作节点归属不一致','action_link_reference_unresolved':'附加操作的连线未匹配','automation_configuration_unassociated':'尚未挂到流程的配置','automation_form_context_conflict':'配置表单与流程表单不同','timeout_condition_missing':'超时条件缺少主定义','timeout_reminder_parent_unresolved':'提醒的父超时配置未匹配','layout_script_decode_unsupported':'脚本编码未支持','layout_shape_unsupported':'布局结构未识别','input_mapping_table_unresolved':'带入映射的来源表未匹配','layout_activity_unknown':'布局活动状态未知'}
    body+='<h2>按流程查看</h2><ul>'+''.join(links)+'</ul><h2>待核对事项</h2>'+table(['待核对事项','数量'],[(issue_names.get(k,k),v) for k,v in sorted(doc['summary']['issue_counts'].items())])
    body+='<h2>未关联配置与来源覆盖</h2><p>以下配置保留原始关系，未挂到某条流程上，不会静默丢弃。</p>'+table(['来源','原始记录','已关联','未关联'],[(name,c['raw_records'],c['associated_records'],c['unassociated_records']) for name,c in doc['source_coverage'].items()])
    body+='<details><summary>查看未关联配置</summary><pre>'+cell(json.dumps(doc['unassociated_configurations'],ensure_ascii=False,indent=2))+'</pre></details>'
    body+='<h2>超时独立条件、平台公式库与调度候选</h2><p>全局公式库和workflow类名匹配的调度定义仅作配置候选，未把它们当作每条流程的实际运行任务。没有读取任务状态、执行日志、任务参数或编号当前值。</p><pre>'+cell(json.dumps(dict(timer_condition_definitions=doc.get('timer_condition_definitions',[]),formula_catalog=doc['formula_catalog'],schedule_candidates=doc['schedule_candidates']),ensure_ascii=False,indent=2))+'</pre>'
    body+='<p>逐来源差异见diff.json；复用的离线分析器代码哈希纳入批次兼容依据。未知字段、编码、动态调用和线上部署仍待核对。</p>'
    save('B05自动处理配置.html','B05自动处理配置',body)
    csv_file(path/'未关联配置.csv',['来源','来源行索引','状态','配置原文'],[[i['source'],i['source_record_index'],i['association_state'],json.dumps(i['configuration'],ensure_ascii=False)] for i in doc['unassociated_configurations']])
    for name,headers,rows in [('布局目录.csv',lh,all_l),('脚本入口.csv',sh,all_s),('布局字段.csv',ph,all_p),('数据带入映射.csv',ih,all_i),('自动配置.csv',ah,all_a)]:csv_file(path/name,headers,rows)

def report_b06(path,raw,doc,diff):
    local=lambda v:datetime.fromisoformat(v).astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    style='<style>body{font:16px/1.7 system-ui;margin:28px;color:#17232d}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ccd3da;padding:7px;vertical-align:top;max-width:600px;overflow-wrap:anywhere}th{background:#eef3f6}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:12px}a{color:#175778}</style>'
    def save(name,title,body):
        (path/name).write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+cell(title)+'</title>'+style+body+'</html>','utf-8')
    def formfile(source,fid):return 'B06表单_'+source+'_'+str(int(fid))+'.html'
    forms={(f['form_source'],f['form_id']):f for f in doc['dictionary']['forms']}
    fields=defaultdict(list);relations=defaultdict(list);models_by_form=defaultdict(list)
    for field in doc['dictionary']['fields']:fields[(field['form_source'],field['form_id'])].append(field)
    for relation in doc['dictionary']['relationships']:relations[(relation['form_source'],relation['form_id'])].append(relation)
    for model in doc['models']:
        if model['form_reference']:models_by_form[(model['form_reference']['form_source'],model['form_reference']['form_id'])].append(model['id'])
    field_headers=['表单来源','表单ID','表单','模块ID','字段ID','名称','名称状态','物理表','数据库列','OA声明类型','实际列类型','控件原值','浏览类型原值','自定义浏览框代码','选项数']
    field_rows=[];relation_rows=[];form_links=[]
    rel_headers=['表单来源','表单ID','父schema','主表','主表键','子schema','明细表','明细键','旧式组过滤','父键结构依据','实际外键约束','关系依据']
    for key,form in forms.items():
        fr=[]
        for f in fields[key]:
            fr.append([key[0],key[1],form['name'],','.join(map(str,models_by_form[key])),f['field_id'],f['name'],f['label_state'],f['physical_table'],f['column_name'],f['declared_db_type'],f['physical_sql_type'],f['html_type_raw'],f['type_raw'],f['custom_browser_code'],len(f['options'])])
        rr=[]
        for r in relations[key]:
            rr.append([key[0],key[1],r.get('parent_schema_reference'),r['parent_table'],r['parent_column'],r.get('child_schema_reference'),r['child_table'],r['child_column'],r['group_id_filter_raw'],r['parent_key_state'],r['database_fk_enforced'],r['basis']])
        field_rows.extend(fr);relation_rows.extend(rr)
        body='<h1>'+cell(form['name'])+' · 字段与主明细</h1><p><a href="B06关联建模与浏览框.html">返回目录</a>。表单'+cell(key[1])+'，来源'+cell(key[0])+'；没有读取业务行。</p>'
        body+='<h2>主明细关系</h2>'+table(rel_headers,rr)+'<h2>字段字典</h2>'+table(field_headers,fr)
        body+='<p>外键、唯一性仅依系统结构。主表金额与多张明细不能直接交叉连接后累计；未匹配字段、空值和布局/脚本效果不能自行补成业务事实。</p>'
        save(formfile(*key),form['name']+'字段字典',body)
        form_links.append('<li><a href="'+formfile(*key)+'">'+cell(form['name'])+' · '+str(key[1])+'</a>：'+str(len(fr))+'字段，'+str(len(rr))+'主明细关系</li>')
    model_index={m['id']:m for m in doc['models']};model_links=[]
    for m in doc['models']:
        ref=m['form_reference'];fid=(ref or {}).get('form_id')
        body='<h1>'+cell(m['name'])+' · 模块定义</h1><p><a href="B06关联建模与浏览框.html">返回目录</a>。模块'+cell(m['id'])+'，实际数据未读取。</p>'
        if ref:body+='<p>表单：<a href="'+formfile('workflow_bill',fid)+'">'+cell(ref['name'])+' · '+cell(fid)+'</a>，主表'+cell(ref['main_table'])+'。</p>'
        else:body+='<p>当前可见表单定义未匹配，原始引用保留。</p>'
        body+='<details><summary>模块配置原值</summary><pre>'+cell(json.dumps(m['configuration'],ensure_ascii=False,indent=2))+'</pre></details>'
        filename='B06模块_'+str(int(m['id']))+'.html';save(filename,m['name']+'模块定义',body)
        model_links.append('<li><a href="'+filename+'">'+cell(m['name'])+' · '+str(m['id'])+'</a>：表单'+cell(fid)+'</li>')
    flow_rows=[]
    for flow in doc['workflow_links']:
        items=[]
        for mid in flow['reachable_model_ids']:
            model=model_index[mid];items.append('<li><a href="B06模块_'+str(mid)+'.html">'+cell(model['name'])+' · '+str(mid)+'</a></li>')
        body='<h1>'+cell(flow['name'])+' · 配置关联</h1><p><a href="B06关联建模与浏览框.html">返回目录</a>。以下是忽略条件/启停的配置引用可达，不能解释为实际数据已流入这些模块。</p>'
        body+='<h2>配置可达模块</h2><ul>'+''.join(items)+'</ul>'
        sets=[s for s in doc['workflow_model_settings'] if (s['workflow_reference'] or {}).get('id')==flow['id'] or any(o['workflow_id']==flow['id'] for o in s.get('action_reference_origins',[]))]
        body+='<details><summary>流程建模设置、字段映射与声明/动作来源</summary><pre>'+cell(json.dumps(sets,ensure_ascii=False,indent=2))+'</pre></details>'
        filename='B06流程_'+str(int(flow['id']))+'.html';save(filename,flow['name']+'配置关联',body)
        flow_rows.append([flow['id'],flow['name'],','.join(map(str,flow['reachable_model_ids'])),flow['visited_reference_count'],'仅配置可达'])
    browser_headers=['代码','匹配状态','注册来源','注册ID','数据源名称/标识','自定义浏览框ID','模块ID','浏览框表单ID','主表','明细返回表','配置返回键','返回键结构状态']
    browser_rows=[];browser_details=[]
    for browser in doc['browsers']:
        if not browser['registrations']:browser_rows.append([browser['code'],browser['lookup_state']]+['']*10)
        for reg in browser['registrations']:
            custom=reg['custom_browser'] or {};form=custom.get('form_reference') or {};model=custom.get('model_reference') or {}
            keys=custom.get('return_keys',[])
            keynames='；'.join(str((k['field_reference'] or {}).get('name') or (k['field_reference'] or {}).get('field_id')) for k in keys)
            browser_rows.append([browser['code'],browser['lookup_state'],reg['source'],reg['id'],reg['configuration'].get('datasourceid'),custom.get('id'),model.get('id'),form.get('form_id'),form.get('main_table'),(custom.get('grain_reference') or {}).get('table_name'),keynames,'；'.join(k['physical_key_state'] for k in keys)])
        browser_details.append('<details><summary>'+cell(browser['code'])+' · '+cell(browser['lookup_state'])+'</summary><pre>'+cell(json.dumps(browser,ensure_ascii=False,indent=2))+'</pre></details>')
    mapping_headers=['设置ID','工作流ID参考','上下文依据','模型ID','映射ID','源字段ID原值','源字段名称','源表','源列','目标字段ID原值','目标字段名称','目标表','目标列','默认值原文（不执行）','候选上下文']
    mapping_rows=[]
    for setting in doc['workflow_model_settings']:
        for row in setting['mappings']:
            cfg=row['configuration'];src=row['workflow_field_reference'] or {};dst=row['model_field_reference'] or {}
            mapping_rows.append([setting['id'],(setting['workflow_reference'] or {}).get('id'),setting['workflow_reference_basis'],(setting['model_reference'] or {}).get('id'),cfg.get('id'),cfg.get('wffieldid'),src.get('name'),src.get('physical_table'),src.get('column_name'),cfg.get('modefieldid'),dst.get('name'),dst.get('physical_table'),dst.get('column_name'),cfg.get('defaultvalue'),json.dumps(row.get('candidate_workflow_mappings',[]),ensure_ascii=False)])
    sql_headers=['来源','配置ID','字段','服务器限定','数据库限定','schema限定','对象候选','本库上下文候选','证据状态']
    sql_rows=[[r['source'],r['source_id'],r['field'],r['server'],r['database'],r['schema'],r['object_name'],r['local_database_candidate'],r['evidence_state']] for r in doc['sql_source_candidates']]
    coverage_rows=[[name,c['raw_records'],c['represented_records'],c['role']] for name,c in doc['source_coverage'].items()]
    s=doc['summary'];body='<h1>B06 关联建模与浏览框 · 待审核</h1><p>配置采集时间：'+cell(local(raw['started_at']))+' 至 '+cell(local(raw['ended_at']))+'。业务单据读取0。</p>'
    body+='<p>流程'+str(s['workflow_count'])+'，模块'+str(s['model_count'])+'，表单'+str(s['form_count'])+'，字段'+str(s['field_count'])+'，浏览框代码'+str(s['browser_code_count'])+'，注册定义'+str(s['registration_count'])+'，流程建模设置'+str(s['workflow_model_setting_count'])+'，字段映射'+str(s['workflow_model_field_mapping_count'])+'。共享对象保留各自引用，不把模块当成流程。</p>'
    body+='<ul>'+''.join('<li>'+cell(v)+'</li>' for v in doc['limitations'])+'</ul>'
    body+='<h2>按流程查看</h2><ul>'+''.join('<li><a href="B06流程_'+str(r[0])+'.html">'+cell(r[1])+' · '+str(r[0])+'</a>：模块引用 '+cell(r[2])+'</li>' for r in flow_rows)+'</ul>'
    body+='<h2>模块目录</h2><ul>'+''.join(model_links)+'</ul><h2>表单与主明细字典</h2><ul>'+''.join(form_links)+'</ul>'
    body+='<h2>浏览框与返回键</h2>'+table(browser_headers,browser_rows)+''.join(browser_details)
    body+='<h2>待核对事项</h2>'+table(['事项代码','引用/记录数'],sorted(s['issue_counts'].items()))
    body+='<p>事项数量可能包含同一对象的多个字段引用，不等于错误数量。浏览框内部负字段与工作流平台字段不套用同一字典，缺默认键解释不自行猜测。</p>'
    body+='<h2>来源覆盖</h2>'+table(['来源','原始行数','目录或校验记录行数','用途'],coverage_rows)
    body+='<p>dependency_validation是已核对的B02/B05不可覆盖来源锚点，不表示新增了业务关系。其他配置完整保存在结构化目录，物理列/键/外键仅来自sys元数据。变更状态：'+cell(diff['status'])+'。</p>'
    body+='<details><summary>未关联项与schema解析</summary><pre>'+cell(json.dumps(dict(unassociated=doc['unassociated_configurations'],physical_object_resolutions=doc['physical_object_resolutions']),ensure_ascii=False,indent=2))+'</pre></details>'
    save('B06关联建模与浏览框.html','B06关联建模与浏览框',body)
    for name,headers,rows in [
        ('流程建模引用.csv',['工作流ID','流程','配置可达模块ID','访问引用节点数','依据'],flow_rows),
        ('浏览框注册.csv',browser_headers,browser_rows),('模块字段.csv',field_headers,field_rows),
        ('主明细关系.csv',rel_headers,relation_rows),('流程建模字段映射.csv',mapping_headers,mapping_rows),
        ('SQL来源候选.csv',sql_headers,sql_rows),('来源覆盖.csv',['来源','原始行数','目录或校验记录行数','用途'],coverage_rows),
        ('未关联项.csv',['来源','来源行索引','配置原文'],[[i['source'],i['source_record_index'],json.dumps(i['configuration'],ensure_ascii=False)] for i in doc['unassociated_configurations']])]:
        csv_file(path/name,headers,rows)


def report_b07(path,raw,doc,diff):
    names=dict(workflow_standard='标准流程报表',workflow_custom='自定义流程统计',model_report='建模报表',model_search='建模查询列表')
    def save(filename,title,body):
        (path/filename).write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+cell(title)+'</title><style>body{font:16px/1.7 system-ui;margin:28px;color:#18222b}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ccd3da;padding:7px;text-align:left;vertical-align:top}th{background:#edf2f6}.scroll{overflow:auto}details{margin:14px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}p{max-width:1100px}</style>'+body+'</html>','utf-8')
    def dump(value):return '<pre>'+cell(json.dumps(value,ensure_ascii=False,indent=2))+'</pre>'
    catalog=[];fieldrows=[];permissionrows=[];filterrows=[];calculationrows=[]
    for r in doc['reports']:
        file='B07_'+r['kind']+'_'+str(int(r['id']))+'.html'
        catalog.append([r['kind'],r['id'],r['name'],r['form_source'],r['form_id'],r['model_id'],','.join(map(str,r['explicit_workflow_ids'])),','.join(map(str,r['form_workflow_candidates'])),len(r['fields']),len(r['permissions']),','.join(map(str,r['model_reference_workflow_candidates'])),file])
        rfields=[]
        for f in r['fields']:
            cfg=f['configuration'];ref=f['field_reference'] or {}
            line=[r['kind'],r['id'],r['name'],f['source'],cfg.get('fieldid'),f['field_state'],cfg.get('fieldidbak'),(f['backup_field_reference'] or {}).get('name'),ref.get('name'),ref.get('physical_table'),ref.get('column_name'),cfg.get('isstat'),cfg.get('isgroup'),cfg.get('isshow'),json.dumps(cfg,ensure_ascii=False)]
            fieldrows.append(line);rfields.append(line[3:])
        for x in r['permissions']:permissionrows.append([r['kind'],r['id'],r['name'],x['source'],x['source_record_index'],json.dumps(x['configuration'],ensure_ascii=False)])
        for x in r['saved_filters']:filterrows.append([r['kind'],r['id'],r['name'],x['source'],x['source_record_index'],(x['field_reference'] or {}).get('name'),json.dumps(x['configuration'],ensure_ascii=False)])
        for x in r['calculations']:calculationrows.append([r['kind'],r['id'],r['name'],x['source'],x['source_record_index'],json.dumps(x['configuration'],ensure_ascii=False)])
        body='<h1>'+cell(r['name'])+' · '+names[r['kind']]+'</h1><p><a href="B07关联报表.html">返回目录</a>。配置定义，业务行读取0。字段按报表自身表单解析；表单候选流程不表示报表已使用这些流程。</p>'
        body+=table(['表单来源','表单编号','依据','模块编号','明确流程列表','同表单流程候选','B06配置可达流程候选'],[[r['form_source'],r['form_id'],r['form_basis'],r['model_id'],r['explicit_workflow_ids'],r['form_workflow_candidates'],r['model_reference_workflow_candidates']]])
        body+='<h2>显示/查询字段与统计原值</h2><p>当前字段编号为空时，备份编号仅供追溯，不作为当前显示字段。</p>'+table(['来源','当前字段ID','绑定状态','备份ID','备份字段参考','当前字段','物理表','列','统计码','分组码','显示码','配置原值'],rfields)
        body+='<h2>报表、过滤和扩展配置</h2>'+dump(r['configuration'])
        body+='<h2>计算表达式</h2>'+dump(r['calculations'])+'<h2>保存的过滤条件</h2>'+dump(r['saved_filters'])
        body+='<h2>共享与表单权限</h2><p>这是配置规则，未展开人员、角色或计算当前用户的实际权限。</p>'+dump(r['permissions'])
        body+='<h2>其他定义</h2>'+dump(r['other_definitions'])
        save(file,r['name'],body)
    coverage=[[k,c['raw_records'],c['represented_records'],c['associated_records'],c['role']] for k,c in doc['source_coverage'].items()]
    body='<h1>B07 关联报表与查询列表 · 待审核</h1><p>配置采集时间：'+cell(raw['started_at'])+' 至 '+cell(raw['ended_at'])+'。业务行读取0，SQL/公式/Java扩展均未执行。</p>'
    body+='<ul>'+''.join('<li>'+cell(x)+'</li>' for x in doc['limitations'])+'</ul>'
    body+=table(['类别','定义数'],[(names[k],v) for k,v in doc['summary']['counts'].items()])
    body+='<h2>报表目录</h2><ul>'+''.join('<li><a href="'+row[-1]+'">'+cell(row[2])+' · '+names[row[0]]+' · '+str(row[1])+'</a></li>' for row in catalog)+'</ul>'
    body+='<h2>待核对事项</h2>'+table(['事项','数量'],[({'report_field_unresolved':'字段引用尚未匹配','report_configuration_unassociated':'配置未取得父定义','report_workflow_list_unparsed':'流程编号列表未解析','report_workflow_form_conflict':'明确流程与报表表单不一致','multiple_detail_aggregation_review':'多明细统计粒度待核对'}.get(k,k),v) for k,v in sorted(doc['summary']['issue_counts'].items())])
    body+='<h2>虚拟表来源定义</h2><p>来源数据源和SQL只保存，不把本库同名表补成已证明来源。</p>'+dump(doc['virtual_forms'])
    body+='<h2>来源覆盖</h2>'+table(['来源','原始记录','目录或校验记录','关联/独立定义','用途'],coverage)
    body+='<p>同口径差异状态：'+cell(diff['status'])+'。完整候选与缺口保存在normalized.json。</p><details><summary>未关联配置</summary>'+dump(doc['unassociated_configurations'])+'</details>'
    save('B07关联报表.html','B07关联报表',body)
    for name,heads,rows in [
        ('报表目录.csv',['类别','ID','报表','表单来源','表单ID','模块ID','明确流程ID','同表单流程候选','字段数','共享规则数','B06配置可达流程候选','页面'],catalog),
        ('报表字段.csv',['类别','报表ID','报表','来源','当前字段ID','绑定状态','备份ID','备份字段参考','当前字段','物理表','列','统计码','分组码','显示码','配置原值'],fieldrows),
        ('报表共享.csv',['类别','报表ID','报表','来源','来源行索引','配置原文'],permissionrows),
        ('保存的过滤条件.csv',['类别','报表ID','报表','来源','来源行索引','字段','配置原文'],filterrows),
        ('计算表达式.csv',['类别','报表ID','报表','来源','来源行索引','表达式配置原文'],calculationrows),
        ('SQL来源候选.csv',['来源','配置ID','字段','schema','对象候选','本库候选','证据'],[[x['source'],x['source_id'],x['field'],x['schema'],x['object_name'],x['local_database_candidate'],x['evidence_state']] for x in doc['sql_source_candidates']]),
        ('来源覆盖.csv',['来源','原始记录','目录或校验记录','关联/独立定义','用途'],coverage),
        ('未关联配置.csv',['来源','来源行索引','配置原文'],[[x['source'],x['source_record_index'],json.dumps(x['configuration'],ensure_ascii=False)] for x in doc['unassociated_configurations']])]:
        csv_file(path/name,heads,rows)


def report_b08(path,raw,doc,diff):
    import hashlib
    def codefile(key):return 'B08代码_'+hashlib.sha256(str(key).encode()).hexdigest()+'.html'
    def save(filename,title,body):
        (path/filename).write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+cell(title)+'</title><style>body{font:16px/1.7 system-ui;margin:28px;color:#18222b}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ccd3da;padding:7px;text-align:left;vertical-align:top}th{background:#edf2f6}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}details{margin:14px 0}</style>'+body+'</html>','utf-8')
    def dump(value):return '<pre>'+cell(json.dumps(value,ensure_ascii=False,indent=2))+'</pre>'
    actionrows=[]
    for a in doc['workflow_actions']:
        c=a['configuration'];t=a['trigger'];actionrows.append([t['workflow_id'],a['id'],c.get('actionname'),a['interface_type_raw'],t['node_id'],t['link_id'],t['phase_raw'],t['order_raw'],t['enabled_raw'],json.dumps(a['definition_candidates'],ensure_ascii=False),','.join(a['code_registration_keys'])])
    ahead=['工作流ID','动作ID','动作名称','接口类型原值','节点ID','路径ID','阶段原值','顺序原值','启停原值','定义候选','代码根标识']
    fieldrows=[]
    for d in doc['dml_definitions']:
        for sql in d['sql_definitions']:
            for m in sql['mappings']:
                c=m['configuration'];ref=m['source_field_candidate'] or {}
                fieldrows.append([d['source'],d['id'],c.get('id'),'DML原始映射码待解释',c.get('fieldname'),c.get('fieldvalue'),ref.get('name'),ref.get('physical_table'),ref.get('column_name'),'','','',json.dumps(c,ensure_ascii=False)])
    for d in doc['workflow_triggers']:
        for m in d['mappings']:
            c=m['configuration'];a=m['model_field_reference'] or {};z=m['workflow_field_reference'] or {}
            fieldrows.append(['mode_triggerworkflowset',d['id'],c.get('id'),'模型字段→流程字段；'+{'target_unselected':'目标未绑定','source_unselected':'源未绑定','configured_target':'已填字段编号，未验证执行'}.get(m['mapping_state'],m['mapping_state']),c.get('modefieldid'),c.get('wffieldid'),a.get('name'),a.get('physical_table'),a.get('column_name'),z.get('name'),z.get('physical_table'),z.get('column_name'),json.dumps(c,ensure_ascii=False)])
    for d in doc['cube_interfaces']:
        for m in d['mappings']:
            c=m['configuration'];f=m['field_reference'] or {}
            fieldrows.append(['CubeInterfaceConfig',d['id'],c.get('id'),'接口字段配置；认证密钥未读',c.get('fieldid'),c.get('isPK'),f.get('name'),f.get('physical_table'),f.get('column_name'),'','','',json.dumps(c,ensure_ascii=False)])
    definitions=[]
    for name,items in [('actionsetting',doc['java_registrations']),('DML',doc['dml_definitions']),('建模触发流程',doc['workflow_triggers']),('Cube字段接口',doc['cube_interfaces']),('WS/SAP其他配置',doc['other_interfaces'])]:
        for x in items:definitions.append([x.get('source',name),x['id'],x.get('name'),json.dumps(x.get('configuration',{}),ensure_ascii=False)])
    file_rows=[];classfiles=defaultdict(list)
    for f in doc['local_source_files']:classfiles[f['class_name']].append(f)
    for f in doc['local_source_files']:
        e=f['evidence'];filename=codefile(f['file_key'])
        body='<h1>'+cell(f['class_name'])+' · 本机代码证据</h1><p><a href="B08接口与字段衔接.html">返回目录</a>。未加载或执行此文件，源码与编译副本不自动视为相同版本。</p>'
        body+=table(['文件','类型','SHA-256','字节数'],[[f['path'],f['kind'],f['sha256'],f.get('size_bytes')]])
        target_names=sorted({x['target_class'] for x in doc['source_graph'].get('edges',[]) if x['source_file_key']==f['file_key']})
        body+='<h2>可见符号文件候选</h2><ul>'+''.join('<li>'+cell(name)+' '+''.join('<a href="'+codefile(t['file_key'])+'">'+cell(t['kind'])+'</a> ' for t in classfiles[name])+'</li>' for name in target_names)+'</ul>'
        body+='<h2>静态字段键、返回、条件、SQL及成员引用</h2><p>词法/常量池候选不等于完整控制流、外部成功或已写回。</p>'+dump(e)
        save(filename,f['class_name'],body)
        file_rows.append([f['file_key'],f['class_name'],f['kind'],f['path'],f['sha256'],len(e.get('field_accesses',[])),len(e.get('returns',[])),len(e.get('sql_fragments',[])),filename])
    flowlinks=[]
    for w in doc['workflow_links']:
        ids=set(w['action_ids']);ar=[row for row in actionrows if row[0]==w['id']]
        body='<h1>'+cell(w['name'])+' · 接口与字段衔接</h1><p><a href="B08接口与字段衔接.html">返回目录</a>。以下均为配置定义，未读取业务单据。</p>'+table(ahead,ar)
        keys={k for a in doc['workflow_actions'] if a['id'] in ids for k in a['code_registration_keys']}
        regs=[r for r in doc['java_registrations'] if r['registration_key'] in keys]
        body+='<h2>Action类注册及本机文件</h2>'
        for r in regs:
            body+='<details><summary>'+cell(r['name'] or r['action_name'])+' · '+cell(r['class_name'])+'</summary>'+dump(r)
            body+='<ul>'+''.join('<li><a href="'+codefile(key)+'">查看本机代码证据</a></li>' for key in r['file_keys'])+'</ul></details>'
        body+='<h2>模型配置引用候选</h2><ul>'+''.join('<li><a href="B08模块_'+str(int(mid))+'.html">'+str(mid)+'</a></li>' for mid in w['reachable_module_candidates'] if any(m['id']==mid for m in doc['models']))+'</ul>'
        body+='<p>触发此流程的模块ID：'+cell(w['trigger_from_module_ids'])+'。动作定义/原始字段映射见总目录对应ID；顺序和启停仅保留原值，未推定外部事务。</p>'
        filename='B08流程_'+str(int(w['id']))+'.html';save(filename,w['name'],body)
        flowlinks.append('<li><a href="'+filename+'">'+cell(w['name'])+' · '+str(w['id'])+'</a>：'+str(len(ar))+'动作</li>')
    parentlinks=[];expandidset={x['id'] for x in doc['module_expansions']}
    for x in doc['module_expansions']:
        if x['source']!='mode_pageexpand_parent':continue
        filename='B08扩展_'+str(int(x['id']))+'.html'
        body='<h1>共用扩展定义 · '+cell(x['id'])+'</h1><p><a href="B08接口与字段衔接.html">返回目录</a>。显式mainid引用，未推定继承或生效。</p>'+dump(x)
        parent=(x['parent_reference'] or {}).get('id')
        if parent in expandidset and any(y['id']==parent and y['source']=='mode_pageexpand_parent' for y in doc['module_expansions']):
            body+='<p><a href="B08扩展_'+str(int(parent))+'.html">查看继续引用的共用扩展</a></p>'
        save(filename,'共用扩展定义',body);parentlinks.append('<li><a href="'+filename+'">共用扩展 '+str(x['id'])+'</a></li>')
    modulelinks=[]
    for m in doc['models']:
        mid=m['id'];items=[x for x in doc['module_expansions'] if x['module_id']==mid]
        body='<h1>'+cell(m['name'])+' · 模块接口配置</h1><p><a href="B08接口与字段衔接.html">返回目录</a>。共用mainid只是显式引用，未继承或覆盖当前模块。</p>'
        body+='<h2>模块定义</h2>'+dump(m)+'<h2>扩展入口及明细</h2>'+dump(items)
        refs=sorted({x['parent_reference']['id'] for x in items if x['parent_reference'] and any(y['id']==x['parent_reference']['id'] and y['source']=='mode_pageexpand_parent' for y in doc['module_expansions'])})
        body+='<h2>显式共用定义参考</h2><ul>'+''.join('<li><a href="B08扩展_'+str(int(parent))+'.html">共用扩展 '+str(parent)+'</a></li>' for parent in refs)+'</ul>'
        body+='<h2>触发流程</h2>'+dump([x for x in doc['workflow_triggers'] if x['configuration'].get('modeid')==mid])
        body+='<h2>接口字段</h2>'+dump([x for x in doc['cube_interfaces'] if x['configuration'].get('modeid')==mid])
        filename='B08模块_'+str(int(mid))+'.html';save(filename,m['name'],body)
        modulelinks.append('<li><a href="'+filename+'">'+cell(m['name'])+' · '+str(mid)+'</a>：'+str(len(items))+'扩展入口</li>')
    erows=[[x['source'],x['id'],x['module_id'],x['configuration'].get('expendname'),(x['parent_reference'] or {}).get('id'),len(x['details']),json.dumps(x['configuration'],ensure_ascii=False),json.dumps(x['details'],ensure_ascii=False)] for x in doc['module_expansions']]
    coverage=[[k,c['raw_records'],c['represented_records'],c['associated_records'],c['role']] for k,c in doc['source_coverage'].items()]
    body='<h1>B08 接口与字段衔接 · 待审核</h1><p>捕获范围时间：'+cell(raw['started_at'])+' 至 '+cell(raw['ended_at'])+'。数据库配置和本机代码分别取证，业务行读取0。</p>'
    body+='<ul>'+''.join('<li>'+cell(x)+'</li>' for x in doc['limitations'])+'</ul>'+table(['项目','数量'],[({'workflow_count':'流程定义','workflow_action_count':'静态动作注册','java_registration_count':'Java类注册','dml_definition_count':'DML定义','module_expand_count':'扩展入口','module_expand_detail_count':'扩展明细','workflow_trigger_count':'触发流程设置','trigger_mapping_count':'触发映射配置行','trigger_configured_target_count':'已填目标编号行','trigger_unselected_target_count':'目标未绑定行','cube_interface_count':'字段接口','cube_mapping_count':'接口字段配置','local_source_file_count':'本机代码证据文件'}.get(k,k),v) for k,v in doc['summary'].items() if k!='issue_counts'])
    body+='<h2>按流程查看</h2><ul>'+''.join(flowlinks)+'</ul><h2>关联模块</h2><ul>'+''.join(modulelinks)+'</ul>'
    body+='<h2>共用扩展定义</h2><ul>'+''.join(parentlinks)+'</ul>'
    body+='<h2>Action注册及未采集参数</h2>'+dump(doc['java_registrations'])
    body+='<h2>DML定义、目标及字段映射原文</h2>'+dump(doc['dml_definitions'])
    body+='<h2>模块触发与成功/失败写回定义</h2>'+dump(doc['workflow_triggers'])
    body+='<h2>其他WS/SAP及Cube接口定义</h2>'+dump(doc['other_interfaces'])+dump(doc['cube_interfaces'])
    body+='<h2>本机代码证据</h2><ul>'+''.join('<li><a href="'+r[-1]+'">'+cell(r[1])+' · '+cell(r[2])+'</a></li>' for r in file_rows)+'</ul>'
    body+='<h2>待核对事项</h2>'+table(['事项','引用/记录数'],[({'interface_definition_unresolved':'接口定义当前未取得','interface_definition_ambiguous':'接口定义候选不唯一','action_node_unresolved':'节点归属待核对','action_link_unresolved':'路径归属待核对','interface_field_unresolved':'字段引用待核对','interface_form_context_conflict':'接口表单上下文不一致','interface_configuration_unassociated':'子配置未取得父项','expand_parent_unresolved':'共用扩展定义未取得','module_external_definition_pending':'外部或任务定义待补'}.get(k,k),v) for k,v in sorted(doc['summary']['issue_counts'].items())])
    body+='<h2>来源覆盖</h2>'+table(['来源','原始行数','目录或校验记录','已关联/独立证据','用途'],coverage)
    body+='<p>同口径差异：'+cell(diff['status'])+'。配置来源、未知编码和完整缺口在normalized.json，不把来源未取得当作不存在。</p>'
    body+='<details><summary>未关联配置</summary>'+dump(doc['unassociated_configurations'])+'</details>'
    save('B08接口与字段衔接.html','B08接口与字段衔接',body)
    for name,heads,rows in [
        ('动作注册.csv',ahead,actionrows),('接口定义.csv',['来源','ID','名称','配置原文'],definitions),
        ('字段映射.csv',['来源','定义ID','映射ID','关系依据','配置源字段/列','配置目标字段/表达式','源字段候选','源表','源列','目标字段','目标表','目标列','配置原文'],fieldrows),
        ('模块扩展.csv',['来源','扩展ID','模块ID','扩展名称','共用mainid参考','明细数','配置原文','完整明细'],erows),
        ('代码证据.csv',['文件键','类候选','文件类型','本机路径','SHA-256','字段键候选数','return数','SQL片段数','页面'],file_rows),
        ('SQL来源候选.csv',['来源','配置ID','字段','对象候选','本库候选','数据源上下文','证据'],[[x['source'],x['source_id'],x['field'],x['object_name'],x['local_database_candidate'],json.dumps(x.get('datasource_context_reference'),ensure_ascii=False),x['evidence_state']] for x in doc['sql_source_candidates']]),
        ('来源覆盖.csv',['来源','原始行数','目录或校验记录','已关联/独立证据','用途'],coverage),
        ('未关联配置.csv',['来源','来源行索引','配置原文'],[[x['source'],x['source_record_index'],json.dumps(x['configuration'],ensure_ascii=False)] for x in doc['unassociated_configurations']])]:
        csv_file(path/name,heads,rows)
