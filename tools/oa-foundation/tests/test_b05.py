import sys,unittest,json,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def fixture():
    field=dict(form_source='workflow_bill',form_id=-7,field_id=101,name='金额',column_name='amount',physical_table='main7')
    seed=dict(workflows=[dict(id=10,name='测试流程',form_source='workflow_bill',form_id=-7,isbill_raw='1')],
              B02=dict(fields=[field]),B03=dict(workflows=[dict(id=10,nodes=[dict(id=1,name='审核')],links=[])]))
    tables=dict(workflow_flownode=[dict(workflowid=10,nodeid=1)],workflow_nodebase=[dict(id=1)],
                workflow_nodelink=[],workflow_nodehtmllayout=[],workflow_formula_htmllayout=[],
                workflow_viewattrlinkage=[],workflow_datainput_entry=[],workflow_datainput_main=[],
                workflow_datainput_table=[],workflow_datainput_field=[],workflow_nodefieldattr=[],
                workflow_addinoperate=[],workflow_code=[],workflow_coderegulate=[],workflow_formula=[],
                workflow_requestwithdraw=[],workflow_function_manage=[],workflow_nodeOverTime=[],
                workflow_nodeOverTime_Detail=[],workflow_nodelinkOverTime=[],schedulesetting=[],rule_maplist=[],rule_base=[],rule_expressionbase=[],rule_expressions=[],rule_mapitem=[])
    return tables,seed

class B05Tests(unittest.TestCase):
    def setUp(self):
        from categories.b05 import normalize
        self.normalize=normalize

    def layout(self,tables,active=1,script=''):
        tables['workflow_nodehtmllayout']=[dict(id=3,workflowid=10,nodeid=1,formid=-7,isbill=1,type=0,isactive=active,
            layoutname='桌面',datajson='{"eformdesign":{"etables":{"main":{"ec":[{"etype":3,"field":101,"id":"0,0"}]}}}}',
            scriptstr=script,scripts=script,initScripts='')]

    def test_duplicate_script_channels_preserved_as_one_inert_source(self):
        tables,seed=fixture();self.layout(tables,script="WfForm.registerCheckEvent(WfForm.OPER_SUBMIT,function(){WfForm.changeFieldValue('field101',{value:2});});")
        flow=self.normalize(tables,seed)['workflows'][0];script=flow['layouts'][0]['scripts'][0]
        self.assertEqual(set(script['channels']),{'scriptstr','scripts'})
        self.assertEqual(script['field_writes'][0]['field_reference']['column_name'],'amount')
        self.assertEqual(script['analysis']['events'][0]['operations'],['submit'])
        self.assertFalse(script['executed'])

    def test_disabled_and_unknown_layouts_do_not_become_active(self):
        tables,seed=fixture();self.layout(tables,active=0,script="fetch('/inert');")
        self.assertFalse(self.normalize(tables,seed)['workflows'][0]['layouts'][0]['active_reference'])
        tables['workflow_nodehtmllayout'][0]['isactive']=None
        self.assertIsNone(self.normalize(tables,seed)['workflows'][0]['layouts'][0]['active_reference'])

    def test_comments_do_not_create_script_writes_or_calls(self):
        tables,seed=fixture();self.layout(tables,script="// fetch('/never'); WfForm.changeFieldValue('field101',{});\nvar x=1;")
        script=self.normalize(tables,seed)['workflows'][0]['layouts'][0]['scripts'][0]
        self.assertEqual(script['analysis']['network_calls'],[])
        self.assertEqual(script['field_writes'],[])

    def test_literal_secrets_not_in_normalized_script_or_analysis(self):
        tables,seed=fixture();self.layout(tables,script="var password='SYNTHETIC_SECRET'; fetch('/inert?token=SYNTHETIC_TOKEN');")
        output=json.dumps(self.normalize(tables,seed))
        self.assertNotIn('SYNTHETIC_SECRET',output);self.assertNotIn('SYNTHETIC_TOKEN',output)

    def test_formula_fields_do_not_borrow_other_form_namespace(self):
        tables,seed=fixture();seed['B02']['fields'].append(dict(form_source='workflow_formbase',form_id=-7,field_id=101,name='错误同号',column_name='wrong',physical_table='old'))
        tables['workflow_formula_htmllayout']=[dict(workflowid=10,nodeid=1,formid=-7,isbill=1,formulakey='a',formula='[main.101]=[main.999]',destfield='101',triggers='0#999')]
        f=self.normalize(tables,seed)['workflows'][0]['formulas'][0]
        self.assertEqual(f['field_references'][0]['field_reference']['column_name'],'amount')
        self.assertIn('automation_field_unresolved',{x['kind'] for x in self.normalize(tables,seed)['issues']})

    def test_data_input_preserves_source_condition_without_executing_it(self):
        tables,seed=fixture()
        tables['workflow_datainput_entry']=[dict(id=4,WorkFlowID=10,TriggerFieldName='field101',enable=1)]
        tables['workflow_datainput_main']=[dict(id=5,entryID=4,WhereClause='businesskey=?',datasourcename='external')]
        tables['workflow_datainput_table']=[dict(id=6,DataInputID=5,TableName='uf_source',Alias='s')]
        tables['workflow_datainput_field']=[dict(id=7,DataInputID=5,TableID=6,Type=1,DBFieldName='value',PageFieldName='field101')]
        item=self.normalize(tables,seed)['workflows'][0]['data_inputs'][0]
        self.assertEqual(item['queries'][0]['mappings'][0]['target_field_reference']['column_name'],'amount')
        self.assertEqual(item['queries'][0]['tables'][0]['TableName'],'uf_source')
        self.assertFalse(item['queries'][0]['executed']);self.assertFalse(item['enabled_reference'])

    def test_orphan_input_mapping_is_not_silently_dropped(self):
        tables,seed=fixture();tables['workflow_datainput_field']=[dict(id=7,DataInputID=999,TableID=6,PageFieldName='field101')]
        with self.assertRaises(ValueError):self.normalize(tables,seed)

    def test_changed_node_scope_rejected(self):
        tables,seed=fixture();tables['workflow_flownode'].append(dict(workflowid=10,nodeid=999))
        with self.assertRaises(ValueError):self.normalize(tables,seed)

    def test_instance_timeout_configuration_is_rejected(self):
        tables,seed=fixture();tables['workflow_nodeOverTime']=[dict(id=1,workflowid=10,nodeid=1,requestid=123)]
        with self.assertRaises(ValueError):self.normalize(tables,seed)

    def test_registry_excludes_sequence_values_and_runtime_jobs(self):
        m=json.loads((Path(__file__).resolve().parents[1]/'registry/B05.json').read_text('utf-8'))
        self.assertNotIn('workflow_codeseq',m['sources'])
        self.assertNotIn('currentCode',m['sources']['workflow_code']['columns'])
        self.assertNotIn('JOB_DATA',json.dumps(m['sources']))
        self.assertIn('requestid',m['sources']['workflow_nodeOverTime']['sql'])

    def test_shared_form_node_attributes_apply_only_to_own_node(self):
        tables,seed=fixture();seed['workflows'].append(dict(seed['workflows'][0],id=20,name='共享表单流程'))
        seed['B03']['workflows'].append(dict(id=20,nodes=[dict(id=2,name='另一个审核')],links=[]))
        tables['workflow_flownode'].append(dict(workflowid=20,nodeid=2));tables['workflow_nodebase'].append(dict(id=2))
        tables['workflow_nodefieldattr']=[dict(id=4,nodeid=2,formid=-7,isbill=1,fieldid=101,attrcontent='default')]
        doc=self.normalize(tables,seed)
        self.assertEqual([len(f['field_attributes']) for f in doc['workflows']],[0,1])

    def test_input_mapping_does_not_borrow_another_query_table(self):
        tables,seed=fixture()
        tables['workflow_datainput_entry']=[dict(id=4,WorkFlowID=10,enable=0)]
        tables['workflow_datainput_main']=[dict(id=5,entryID=4),dict(id=8,entryID=4)]
        tables['workflow_datainput_table']=[dict(id=6,DataInputID=8,TableName='other')]
        tables['workflow_datainput_field']=[dict(id=7,DataInputID=5,TableID=6,PageFieldName='field101')]
        item=self.normalize(tables,seed)['workflows'][0]['data_inputs'][0]['queries'][0]['mappings'][0]
        self.assertIsNone(item['source_table_reference'])

    def test_formula_uses_own_form_context_when_configuration_conflicts(self):
        tables,seed=fixture()
        seed['B02']['fields'].append(dict(form_source='workflow_formbase',form_id=8,field_id=101,name='规则自身字段',column_name='own_context',physical_table='old'))
        tables['workflow_formula_htmllayout']=[dict(workflowid=10,nodeid=1,formid=8,isbill=0,formula='[main.101]')]
        item=self.normalize(tables,seed)['workflows'][0]['formulas'][0]
        self.assertEqual(item['field_references'][0]['field_reference']['column_name'],'own_context')

    def test_unassociated_form_node_configuration_is_preserved_with_gap(self):
        tables,seed=fixture();tables['workflow_nodefieldattr']=[dict(id=77,nodeid=999,formid=-7,isbill=1,fieldid=101,attrcontent='default')]
        doc=self.normalize(tables,seed)
        self.assertEqual(len(doc.get('unassociated_configurations',[])),1)
        self.assertEqual(doc['unassociated_configurations'][0]['configuration']['id'],77)
        self.assertIn('automation_configuration_unassociated',{i['kind'] for i in doc['issues']})

    def test_url_userinfo_query_secrets_and_nested_sensitive_keys_are_redacted(self):
        tables,seed=fixture();self.layout(tables,script="fetch('https://test:SYNTHETIC_URL_PASS@example.invalid/path?client_secret=SYNTHETIC_CLIENT_SECRET');")
        tables['workflow_requestwithdraw']=[dict(id=1,workflowid=10,client_secret='SYNTHETIC_NESTED_SECRET')]
        output=json.dumps(self.normalize(tables,seed))
        for secret in ['SYNTHETIC_URL_PASS','SYNTHETIC_CLIENT_SECRET','SYNTHETIC_NESTED_SECRET']:self.assertNotIn(secret,output)

    def test_plain_json_layout_is_parsed_without_javascript_lexing(self):
        from unittest.mock import patch
        tables,seed=fixture();self.layout(tables)
        with patch('categories.b05.decode_layout_text',side_effect=AssertionError('Plain JSON is not JavaScript')):
            layout=self.normalize(tables,seed)['workflows'][0]['layouts'][0]
        self.assertTrue(layout['placements_known']);self.assertEqual(len(layout['placements']),1)

    def test_platform_layout_control_is_not_a_missing_business_field(self):
        tables,seed=fixture();self.layout(tables)
        tables['workflow_nodehtmllayout'][0]['datajson']=tables['workflow_nodehtmllayout'][0]['datajson'].replace('101','-1')
        d=self.normalize(tables,seed);ref=d['workflows'][0]['layouts'][0]['placements'][0]['field_reference']
        self.assertEqual((ref or {}).get('namespace'),'platform')
        self.assertNotIn('automation_field_unresolved',{i['kind'] for i in d['issues']})

    def test_layout_uses_own_declared_form_namespace(self):
        tables,seed=fixture();self.layout(tables,script="WfForm.changeFieldValue('field101',{value:2});")
        seed['B02']['fields'].append(dict(form_source='workflow_formbase',form_id=8,field_id=101,name='布局自身字段',column_name='layout_context',physical_table='old'))
        tables['workflow_nodehtmllayout'][0].update(formid=8,isbill=0)
        layout=self.normalize(tables,seed)['workflows'][0]['layouts'][0]
        self.assertEqual(layout['placements'][0]['field_reference']['column_name'],'layout_context')
        self.assertEqual(layout['scripts'][0]['field_writes'][0]['field_reference']['column_name'],'layout_context')

    def test_timeout_condition_keeps_own_form_and_expression_tree(self):
        tables,seed=fixture()
        seed['B02']['fields'].append(dict(form_source='workflow_formbase',form_id=8,field_id=101,name='条件自身字段',column_name='timer_context',physical_table='old'))
        tables['workflow_nodeOverTime']=[dict(id=81,workflowid=10,nodeid=1,requestid=0,ruleid='90')]
        tables['rule_base']=[dict(id=90,formid=8,isbill=0,rulesrc=7)]
        tables['rule_expressionbase']=[dict(id=91,ruleid=90,datafield='field101')]
        tables['rule_expressions']=[dict(id=92,ruleid=90,expressionid=91)]
        d=self.normalize(tables,seed)
        condition=d['workflows'][0]['overtime'][0].get('independent_condition')
        self.assertIsNotNone(condition)
        self.assertEqual(condition['terms'][0]['field_reference']['column_name'],'timer_context')
        self.assertEqual(len(condition['expression_tree']),1)
        self.assertFalse(condition['evaluated'])

    def test_timeout_reminder_points_to_its_static_parent(self):
        tables,seed=fixture()
        tables['workflow_nodeOverTime']=[dict(id=81,workflowid=10,nodeid=1,requestid=0,ruleid=None)]
        tables['workflow_nodeOverTime_Detail']=[dict(id=82,workflowid=10,nodeid=1,overtimeid='81')]
        d=self.normalize(tables,seed)
        ref=d['workflows'][0]['overtime'][1].get('parent_timeout_reference')
        self.assertEqual((ref or {}).get('id'),81)

    def test_link_action_binds_to_route_and_conflicting_node_stays_pending(self):
        tables,seed=fixture();seed['B03']['workflows'][0]['routes']=[dict(id=3,name='提交线',from_node=1,to_node=1)]
        tables['workflow_addinoperate']=[dict(id=4,workflowid=10,isnode=0,objid=3,fieldid=101),dict(id=5,workflowid=10,isnode=1,objid=999,fieldid=101)]
        d=self.normalize(tables,seed);actions=d['workflows'][0]['actions']
        self.assertEqual(actions[0].get('binding_kind'),'link')
        self.assertEqual(actions[0]['binding_reference']['id'],3)
        self.assertEqual(actions[1]['node_scope_state'],'conflict_pending')
        self.assertEqual(d['source_coverage']['workflow_addinoperate']['associated_records'],2)

    def test_missing_timeout_base_keeps_all_expression_and_mapping_candidates(self):
        tables,seed=fixture();tables['workflow_nodeOverTime']=[dict(id=81,workflowid=10,nodeid=1,requestid=0,ruleid='90')]
        for source in ['rule_maplist','rule_expressionbase','rule_expressions','rule_mapitem']:
            tables[source]=[dict(id=91,ruleid=90,datafield='field101')]
        d=self.normalize(tables,seed);candidate=d['workflows'][0]['overtime'][0]['independent_condition']
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate['definition_state'],'missing')
        self.assertIsNone(candidate['terms'][0]['field_reference'])
        self.assertEqual([len(candidate[k]) for k in ['terms','expression_tree','mapping_candidates','parameter_mapping_candidates']],[1,1,1,1])
        for source in ['rule_maplist','rule_expressionbase','rule_expressions','rule_mapitem']:
            self.assertEqual(d['source_coverage'][source],dict(raw_records=1,associated_records=1,unassociated_records=0))
        self.assertIn('timeout_condition_missing',{i['kind'] for i in d['issues']})

if __name__=='__main__':unittest.main()
