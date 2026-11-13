import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def fixture():
    seed=dict(workflows=[dict(id=10,name='测试流程',form_id=-7,isbill_raw='1',form_source='workflow_bill')],B02=dict(fields=[dict(form_id=-7,form_source='workflow_bill',field_id=101,name='申请金额',column_name='amount',physical_table='formtable_main_7')]))
    tables={
      'workflow_flownode':[dict(workflowid=10,nodeid=1,nodetype='0'),dict(workflowid=10,nodeid=2,nodetype='3')],
      'workflow_nodebase':[dict(id=1,nodename='开始',isstart='1',isend='0'),dict(id=2,nodename='结束',isstart='0',isend='1')],
      'workflow_nodelink':[dict(id=20,workflowid=10,nodeid=1,destnodeid=2,linkname='提交',condition='',conditioncn='',newconditioncn='',newrule='',ruleRelationship='0',isreject='0')],
      'rule_maplist':[dict(id=1,wfid=10,linkid=20,ruleid=30,rulesrc=1,isused=1,nm=0,rowidenty=0)],
      'rule_base':[dict(id=30,rulesrc=2,formid=-7,linkid=20,isbill=1,rulename='金额条件',condit='amount > 10')],
      'rule_expressionbase':[dict(id=40,ruleid=30,datafield='101',datafieldtext='金额',compareoption1=1,elementvalue1='10')],
      'rule_expressions':[dict(id=50,ruleid=30,relation=0,expids='',expbaseid=40)]
    }
    return tables,seed
class B03Tests(unittest.TestCase):
    def setUp(self):
        from categories.b03 import normalize
        self.normalize=normalize
    def test_empty_legacy_condition_keeps_independent_rule(self):
        tables,seed=fixture();d=self.normalize(tables,seed);route=d['workflows'][0]['routes'][0]
        self.assertEqual(route['condition_state'],'independent_rules_present')
        self.assertEqual(route['rules'][0]['condition_sql_raw'],'amount > 10')
        self.assertFalse(d['runtime_verified'])
    def test_rule_source_and_workflow_scope_not_confused(self):
        tables,seed=fixture();tables['rule_maplist'] += [dict(id=2,wfid=10,linkid=20,ruleid=99,rulesrc=2,isused=1,nm=0,rowidenty=0),dict(id=3,wfid=11,linkid=20,ruleid=30,rulesrc=1,isused=1,nm=0,rowidenty=0)]
        d=self.normalize(tables,seed)
        self.assertEqual(len(d['workflows'][0]['routes'][0]['rules']),1)
        self.assertEqual(d['workflows'][0]['routes'][0]['unresolved_rule_candidates'][0]['rule_id'],30)
        self.assertIn('mapping_workflow_scope_conflict',{i['kind'] for i in d['issues']})
    def test_expression_field_links_to_correct_form(self):
        tables,seed=fixture();d=self.normalize(tables,seed)
        term=d['workflows'][0]['routes'][0]['rules'][0]['terms'][0]
        self.assertEqual(term['field_reference']['name'],'申请金额')
    def test_dangling_node_and_missing_rule_remain_gaps(self):
        tables,seed=fixture();tables['workflow_nodelink'][0]['destnodeid']=999;tables['rule_base']=[]
        d=self.normalize(tables,seed)
        self.assertTrue({'route_endpoint_missing','rule_definition_missing'}<={i['kind'] for i in d['issues']})
        self.assertEqual(d['workflows'][0]['routes'][0]['condition_state'],'rule_reference_unresolved')
    def test_loop_is_topology_not_runtime_or_configuration_error(self):
        tables,seed=fixture();tables['workflow_nodelink'].append(dict(tables['workflow_nodelink'][0],id=21,nodeid=2,destnodeid=1,isreject='1'))
        d=self.normalize(tables,seed)
        self.assertTrue(d['workflows'][0]['topology']['has_cycle'])
        self.assertFalse(d['runtime_verified'])
    def test_no_condition_is_not_claimed_unconditional(self):
        tables,seed=fixture();tables['rule_maplist']=[]
        d=self.normalize(tables,seed)
        self.assertEqual(d['workflows'][0]['routes'][0]['condition_state'],'no_condition_definition_observed')
    def test_expression_cycles_are_reported_without_evaluation(self):
        tables,seed=fixture();tables['rule_expressions']=[dict(id=50,ruleid=30,relation=0,expids='51',expbaseid=0),dict(id=51,ruleid=30,relation=1,expids='50',expbaseid=0)]
        d=self.normalize(tables,seed)
        self.assertIn('expression_cycle',{i['kind'] for i in d['issues']})
    def test_duplicate_node_binding_rejects_ambiguous_model(self):
        tables,seed=fixture();tables['workflow_flownode'].append(dict(tables['workflow_flownode'][0]))
        with self.assertRaises(ValueError):self.normalize(tables,seed)
    def test_rule_base_source_code_is_not_guessed_from_another_dictionary(self):
        tables,seed=fixture();tables['rule_base'][0]['rulesrc']=1
        doc=self.normalize(tables,seed)
        self.assertNotIn('rule_base_source_code_unconfirmed',{i['kind'] for i in doc['issues']})
        self.assertEqual(doc['workflows'][0]['routes'][0]['rules'][0]['rule_source_raw'],1)

    def test_rule_form_namespace_cannot_borrow_same_id_field(self):
        tables,seed=fixture();tables['rule_base'][0]['isbill']=0
        d=self.normalize(tables,seed);rule=d['workflows'][0]['routes'][0]['rules'][0]
        self.assertIsNone(rule['terms'][0]['field_reference'])
        self.assertIn('rule_form_namespace_differs',{i['kind'] for i in d['issues']})

    def test_rule_field_uses_rule_form_not_target_form(self):
        tables,seed=fixture();tables['rule_base'][0]['formid']=-8
        seed['B02']['fields'].append(dict(form_id=-8,form_source='workflow_bill',field_id=101,name='规则所属表字段',column_name='other_amount',physical_table='formtable_main_8'))
        d=self.normalize(tables,seed)
        field=d['workflows'][0]['routes'][0]['rules'][0]['terms'][0]['field_reference']
        self.assertEqual(field['physical_table'],'formtable_main_8')

    def test_missing_rule_keeps_complete_mapping_candidate(self):
        tables,seed=fixture();tables['rule_base']=[]
        d=self.normalize(tables,seed)
        candidate=d['workflows'][0]['routes'][0]['unresolved_rule_candidates'][0]
        self.assertEqual(candidate['definition_state'],'missing')
        self.assertEqual(candidate['mapping']['ruleid'],30)

if __name__=='__main__':unittest.main()
