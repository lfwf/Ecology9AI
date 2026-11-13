import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def fixture():
    seed=dict(workflows=[dict(id=10,name='测试流程',form_id=-7,isbill_raw='1',form_source='workflow_bill')],
      B02=dict(fields=[dict(form_id=-7,form_source='workflow_bill',field_id=101,name='金额',column_name='amount',physical_table='main7')]),
      B03=dict(workflows=[dict(id=10,nodes=[dict(id=1,name='审核',type_raw='1')])]))
    tables={
      'workflow_flownode':[dict(workflowid=10,nodeid=1,nodetype='1')],
      'workflow_nodebase':[dict(id=1,nodename='审核',isstart='0',isend='0')],
      'workflow_nodegroup':[dict(id=20,nodeid=1,groupname='责任组',canview=1)],
      'workflow_groupdetail':[dict(id=30,groupid=20,type=2,objid=5,level_n=0,level2_n=0,orders=0,signorder='1',CONDITIONS='',CONDITIONCN='',ruleRelationship='0')],
      'workflow_nodeform':[dict(nodeid=1,fieldid=101,isview='1',isedit='0',ismandatory='1',isonlyshow='0')],
      'workflow_NodeFormGroup':[dict(nodeid=1,groupid=1,isadd='1',isedit='1',isdelete='0')],
      'HrmRoles':[dict(id=5,rolesname='审核角色',rolesmark='审核角色')],
      'HrmRoleMembers':[dict(id=1,roleid=5,resourceid=7,resourcetype=1,rolelevel='0'),dict(id=2,roleid=5,resourceid=7,resourcetype=3,rolelevel='0')],
      'HrmResource':[dict(id=7,lastname='测试人员',status=0,departmentid=7,subcompanyid1=1,managerid=0)],
      'HrmDepartment':[dict(id=7,departmentname='测试部门',supdepid=0,subcompanyid1=1,canceled='0')],
      'HrmSubCompany':[dict(id=1,subcompanyname='测试分部',supsubcomid=0,canceled='0')],
      'workflow_hrmoperator':[],'HrmJobTitles':[],'rule_maplist':[],'rule_base':[],'rule_expressionbase':[],'rule_expressions':[],'rule_mapitem':[]
    }
    return tables,seed
class B04Tests(unittest.TestCase):
    def setUp(self):
        from categories.b04 import normalize
        self.normalize=normalize
    def test_role_member_resource_namespaces_stay_separate(self):
        tables,seed=fixture();d=self.normalize(tables,seed)
        members=d['workflows'][0]['nodes'][0]['groups'][0]['operator_rules'][0]['role_members']
        self.assertEqual([m['target_kind'] for m in members],['person','department'])
        self.assertEqual([m['target_name'] for m in members],['测试人员','测试部门'])
        self.assertFalse(d['actual_operators_resolved'])
    def test_missing_permission_record_is_unknown_not_hidden(self):
        tables,seed=fixture();tables['workflow_nodeform']=[]
        n=self.normalize(tables,seed)['workflows'][0]['nodes'][0]
        self.assertEqual(n['missing_permission_field_ids'],[101])
        self.assertEqual(n['missing_permission_meaning'],'unknown_not_denied')
    def test_blank_flag_is_unknown_and_readonly_required_needs_assignment_check(self):
        tables,seed=fixture();d=self.normalize(tables,seed)
        self.assertIn('required_without_base_edit_permission',{i['kind'] for i in d['issues']})
        tables['workflow_nodeform'][0]['isview']=''
        p=self.normalize(tables,seed)['workflows'][0]['nodes'][0]['permissions'][0]
        self.assertIsNone(p['visible_base'])
    def test_dynamic_creator_rule_does_not_resolve_actual_person(self):
        tables,seed=fixture();tables['workflow_groupdetail'][0].update(type=17,objid=7)
        r=self.normalize(tables,seed)['workflows'][0]['nodes'][0]['groups'][0]['operator_rules'][0]
        self.assertEqual(r['target_kind'],'creator_dynamic')
        self.assertIsNone(r['target_reference'])
    def test_unknown_operator_and_sign_codes_remain_raw(self):
        tables,seed=fixture();tables['workflow_groupdetail'][0].update(type=999,signorder='x')
        d=self.normalize(tables,seed);r=d['workflows'][0]['nodes'][0]['groups'][0]['operator_rules'][0]
        self.assertEqual(r['operator_type_raw'],999);self.assertEqual(r['signorder_raw'],'x')
        self.assertIn('unknown_operator_type',{i['kind'] for i in d['issues']})
    def test_empty_operator_group_is_visible(self):
        tables,seed=fixture();tables['workflow_groupdetail']=[]
        d=self.normalize(tables,seed)
        self.assertIn('operator_group_without_rules',{i['kind'] for i in d['issues']})
    def test_same_id_permission_uses_target_form_namespace(self):
        tables,seed=fixture()
        seed['B02']['fields'].append(dict(form_id=-7,form_source='workflow_formbase',field_id=101,name='旧表字段',column_name='subject',physical_table='workflow_form'))
        p=self.normalize(tables,seed)['workflows'][0]['nodes'][0]['permissions'][0]
        self.assertEqual(p['field_reference']['name'],'金额')
    def test_changed_static_node_scope_rejects_publication(self):
        tables,seed=fixture();tables['workflow_flownode'].append(dict(workflowid=10,nodeid=2,nodetype='1'))
        with self.assertRaises(ValueError):self.normalize(tables,seed)

    def test_configuration_outside_dependency_nodes_is_not_silently_lost(self):
        tables,seed=fixture();tables['workflow_nodeform'].append(dict(nodeid=999,fieldid=101,isview='1',isedit='1',ismandatory='0',isonlyshow='0'))
        with self.assertRaises(ValueError):self.normalize(tables,seed)

    def test_detail_group_zero_uses_ordered_sequence_not_registration_id(self):
        tables,seed=fixture();tables['workflow_NodeFormGroup'][0]['groupid']=0
        seed['B02']['forms']=[dict(form_source='workflow_bill',form_id=-7,details=[dict(detail_id=200,table_name='second',order_raw=20),dict(detail_id=100,table_name='first',order_raw=10)])]
        d=self.normalize(tables,seed)
        self.assertEqual(d['workflows'][0]['nodes'][0]['detail_permissions'][0]['detail_reference']['table_name'],'first')

    def test_registry_limits_hr_read_to_six_allowed_columns(self):
        import json
        method=json.loads((Path(__file__).resolve().parents[1]/'registry/B04.json').read_text('utf-8'))
        self.assertEqual(set(method['sources']['HrmResource']['columns']),{'id','lastname','status','departmentid','subcompanyid1','managerid'})

    def test_fixed_person_list_is_configuration_and_can_have_multiple_people(self):
        tables,seed=fixture();tables['workflow_groupdetail'][0].update(type=3,objid=None)
        tables['HrmResource'].append(dict(id=8,lastname='第二位测试人员',status=0,departmentid=7,subcompanyid1=1,managerid=0))
        tables['workflow_hrmoperator']=[dict(type=None,objid='7',groupid='20',groupdetailid='30',signorder='1',orders=0),dict(type='3',objid='8',groupid='20',groupdetailid='30',signorder='0',orders=1)]
        d=self.normalize(tables,seed);r=d['workflows'][0]['nodes'][0]['groups'][0]['operator_rules'][0]
        self.assertEqual([x['id'] for x in r.get('target_references',[])],[7,8])
        self.assertEqual(len(r.get('configured_objects',[])),2)
        self.assertNotIn('operator_target_reference_unresolved',{i['kind'] for i in d['issues']})
        self.assertFalse(r['actual_operators_resolved'])

    def test_fixed_person_list_conflicting_group_and_null_objects_are_preserved(self):
        tables,seed=fixture();tables['workflow_groupdetail'][0].update(type=3,objid=None)
        tables['workflow_hrmoperator']=[dict(type='3',objid='7',groupid='999',groupdetailid='30',signorder='1',orders=0),dict(type=None,objid=None,groupid='20',groupdetailid='30',signorder=None,orders=1)]
        d=self.normalize(tables,seed);r=d['workflows'][0]['nodes'][0]['groups'][0]['operator_rules'][0]
        self.assertEqual(len(r.get('configured_objects',[])),2)
        self.assertEqual(r.get('target_references'),[])
        self.assertIn('operator_object_group_conflict',{i['kind'] for i in d['issues']})
        self.assertIn('operator_object_person_unresolved',{i['kind'] for i in d['issues']})

    def test_orphan_operator_object_does_not_disappear(self):
        tables,seed=fixture();tables['workflow_hrmoperator']=[dict(type='3',objid='7',groupid='20',groupdetailid='999')]
        with self.assertRaises(ValueError):self.normalize(tables,seed)

    def test_platform_fields_use_separate_namespace(self):
        tables,seed=fixture();tables['workflow_nodeform'][0]['fieldid']=-9
        d=self.normalize(tables,seed);p=d['workflows'][0]['nodes'][0]['permissions'][0]
        self.assertEqual((p['field_reference'] or {}).get('name'),'打印次数')
        self.assertEqual((p['field_reference'] or {}).get('namespace'),'platform')
        self.assertNotIn('permission_field_unresolved',{i['kind'] for i in d['issues']})

    def test_everyone_rule_is_dynamic_without_whole_employee_expansion(self):
        tables,seed=fixture();tables['workflow_groupdetail'][0].update(type=4,objid=None)
        r=self.normalize(tables,seed)['workflows'][0]['nodes'][0]['groups'][0]['operator_rules'][0]
        self.assertEqual(r['target_kind'],'everyone_dynamic');self.assertTrue(r['runtime_dependency'])
        self.assertIsNone(r['target_reference'])

    def test_field_manager_rule_references_field_without_resolving_people(self):
        tables,seed=fixture();tables['workflow_groupdetail'][0].update(type=6,objid=101)
        r=self.normalize(tables,seed)['workflows'][0]['nodes'][0]['groups'][0]['operator_rules'][0]
        self.assertEqual(r['target_kind'],'form_field_manager_dynamic')
        self.assertEqual(r['target_reference']['field_id'],101);self.assertFalse(r['actual_operators_resolved'])

if __name__=='__main__':unittest.main()
