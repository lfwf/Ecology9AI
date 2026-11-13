import sys,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def fixture():
    seed={'workflows':[{'id':10,'name':'流程甲','form_id':-7,'form_source':'workflow_bill','isbill_raw':'1'},
                       {'id':20,'name':'旧流程','form_id':14,'form_source':'workflow_formbase','isbill_raw':'0'}],
          'B03':{'workflows':[{'id':10,'nodes':[{'id':100,'name':'审批'}],'routes':[{'id':200}]},{'id':20,'nodes':[],'routes':[]}]},
          'B06':{'dictionary':{'fields':[{'form_source':'workflow_bill','form_id':-7,'field_id':11,'name':'流程字段','column_name':'code','physical_table':'formtable_main_7'},
                   {'form_source':'workflow_formbase','form_id':14,'field_id':11,'name':'旧字段','column_name':'oldcode','physical_table':'workflow_form'},
                   {'form_source':'workflow_bill','form_id':-9,'field_id':50,'name':'模型字段','column_name':'master_code','physical_table':'uf_master'}]},
                 'workflow_links':[{'id':10,'reachable_model_ids':[8]}]},
          '_source_database':'fixture',
          '_source_graph':{'registrations':[{'registration_id':'actionsetting:2','file_keys':['source1'],'lookup_state':'files_visible'}],'edges':[],'closed':True}}
    tables={
      'workflowactionset':[{'id':101,'workflowid':10,'nodeid':100,'nodelinkid':0,'interfaceid':'REG_NAME','interfacetype':'3','ispreoperator':'1','actionorder':2,'isused':'0'},
                           {'id':102,'workflowid':10,'nodeid':0,'nodelinkid':200,'interfaceid':'2','interfacetype':'1','actionorder':1}],
      'actionsetting':[{'id':2,'actionname':'REG_NAME','actionclass':'demo.A','actionshowname':'接口甲'}],
      'actionsettingdetail':[{'id':3,'actionid':2,'attrname':'url','isdatasource':'0'}],
      'formactionset':[{'id':2,'formid':-7,'isbill':1,'dmltype':'x','dmlactionname':'DML甲'}],
      'formactionsqlset':[{'id':4,'actionid':2,'dmlsql':'update ext_target set code=?'}],
      'formactionfieldmap':[{'id':5,'actionsqlsetid':4,'fieldname':'external_code','fieldvalue':'field11','maptype':'x'}],
      'modeinfo':[{'id':8,'modename':'模块甲','formid':-9}],
      'mode_pageexpand':[{'id':1,'modeid':8,'mainid':2,'expendname':'扩展甲'}],
      'mode_pageexpand_parent':[{'id':2,'modeid':0,'mainid':0,'expendname':'共用原项'}],
      'mode_pageexpanddetail':[{'id':6,'mainid':1,'interfacetype':1,'triggerworkflowsetid':7,'ordernum':1}],
      'mode_triggerworkflowset':[{'id':7,'modeid':8,'workflowid':20,'triggername':'触发旧流程','successwriteback':'raw success','failwriteback':'raw failure'}],
      'mode_triggerworkflowsetdetail':[{'id':8,'mainid':7,'modefieldid':50,'wffieldid':11,'defaultvalue':'EXEC never_run'}],
      'CubeInterfaceConfig':[{'id':9,'modeid':8,'interfaceName':'字段接口','interfacetype':1}],
      'cubeInterfaceConfigDetail':[{'id':10,'mainid':9,'fieldid':50,'isPK':1,'tablename':'uf_master'}],
      'local_source_files':[{'file_key':'source1','class_name':'demo.A','path':'synthetic/A.java','sha256':'fixturehash','kind':'source','runtime_loaded_verified':False,
                            'evidence':{'field_accesses':[{'field_literal':'code','line':4}],'returns':[{'expression':'doResult(result)','line':9}],'sql_fragments':[],'calls':[],'control_fragments':[]}}]}
    return tables,seed
def normalize(t,s):
    from categories import b08
    return b08.normalize(t,s)
class B08Tests(unittest.TestCase):
    def test_action_key_is_actionname_not_numeric_registration_id(self):
        t,s=fixture();n=normalize(t,s);a=n['workflow_actions'][0]
        self.assertEqual(a['definition_candidates'],[{'source':'actionsetting','id':2}])
        self.assertEqual(a['code_registration_keys'],['actionsetting:2'])
        self.assertEqual(a['trigger']['node_id'],100)
    def test_same_number_interface_types_do_not_share_definitions(self):
        t,s=fixture();n=normalize(t,s);a=n['workflow_actions'][1]
        self.assertEqual(a['definition_candidates'],[{'source':'formactionset','id':2}])
        self.assertEqual(a['code_registration_keys'],[])
    def test_multiple_named_registrations_remain_candidates(self):
        t,s=fixture();t['actionsetting'].append(dict(t['actionsetting'][0],id=3,actionclass='demo.B'))
        n=normalize(t,s);self.assertEqual(len(n['workflow_actions'][0]['definition_candidates']),2)
        self.assertIn('interface_definition_ambiguous',[x['kind'] for x in n['issues']])
    def test_trigger_mapping_uses_source_model_and_target_workflow_namespaces(self):
        t,s=fixture();n=normalize(t,s);m=n['workflow_triggers'][0]['mappings'][0]
        self.assertEqual(m['model_field_reference']['name'],'模型字段')
        self.assertEqual(m['workflow_field_reference']['name'],'旧字段')
        self.assertEqual(m['configuration']['defaultvalue'],'EXEC never_run')
    def test_form_context_conflict_is_preserved_and_not_overridden(self):
        t,s=fixture();t['formactionset'][0]['formid']=777;n=normalize(t,s)
        self.assertIn('interface_form_context_conflict',[x['kind'] for x in n['issues']])
        self.assertEqual(n['dml_definitions'][0]['context']['form_id'],777)
    def test_static_node_scope_conflict_is_visible(self):
        t,s=fixture();t['workflowactionset'][0]['nodeid']=999
        self.assertIn('action_node_unresolved',[x['kind'] for x in normalize(t,s)['issues']])
    def test_unknown_interface_type_does_not_borrow_known_id(self):
        t,s=fixture();t['workflowactionset'][0]['interfacetype']='99';t['workflowactionset'][0]['interfaceid']='2'
        n=normalize(t,s);self.assertEqual(n['workflow_actions'][0]['definition_candidates'],[])
        self.assertIn('interface_type_unexplained',[x['kind'] for x in n['issues']])
    def test_common_parent_is_a_reference_and_does_not_replace_child_module(self):
        t,s=fixture();n=normalize(t,s);r=next(x for x in n['module_expansions'] if x['id']==1)
        self.assertEqual(r['module_id'],8);self.assertEqual(r['parent_reference']['id'],2)
        self.assertEqual(len(r['details']),1)
    def test_orphan_children_and_all_coverage_rows_remain_visible(self):
        t,s=fixture();t['mode_triggerworkflowsetdetail'].append({'id':9,'mainid':404,'modefieldid':50,'wffieldid':11})
        n=normalize(t,s)
        self.assertTrue(any(x['source']=='mode_triggerworkflowsetdetail' and x['source_record_index']==1 for x in n['unassociated_configurations']))
        for name,rows in t.items():self.assertEqual(n['source_coverage'][name]['represented_records'],len(rows))
    def test_api_key_property_values_and_markup_are_safe_in_normalized_outputs(self):
        t,s=fixture();t['CubeInterfaceConfig'][0]['interfacePK']='fixtureApiSecret'
        t['actionsettingdetail'][0]['attrvalue']='fixtureAttributeSecret'
        t['mode_pageexpand'][0]['showcondition']='<password>fixtureXmlSecret</password>'
        n=normalize(t,s);text=json.dumps(n)
        for secret in ['fixtureApiSecret','fixtureAttributeSecret','fixtureXmlSecret']:self.assertNotIn(secret,text)
        self.assertEqual(n['cube_interfaces'][0]['mappings'][0]['field_reference']['name'],'模型字段')
        self.assertFalse(n['runtime_verified'])
    def test_uncollected_action_property_is_explicit_and_code_outcome_is_not_success_fact(self):
        t,s=fixture();n=normalize(t,s)
        self.assertEqual(n['java_registrations'][0]['parameters'][0]['value_state'],'not_collected')
        self.assertEqual(n['java_registrations'][0]['file_keys'],['source1'])
        self.assertFalse(n['java_registrations'][0]['runtime_verified'])
    def test_source_input_uses_namespaced_origins_and_literal_module_java_is_not_executed(self):
        from interface_sources import registration_rows
        t,s=fixture();t['mode_pageexpanddetail'].append({'id':20,'mainid':1,'interfacetype':3,'interfacevalue':'demo.ModuleHook'})
        rows=registration_rows(t)
        self.assertTrue(any(x['id']=='actionsetting:2' and x['actionclass']=='demo.A' for x in rows))
        self.assertTrue(any(x['id']=='mode_pageexpanddetail:20:interfacevalue' and x['actionclass']=='demo.ModuleHook' for x in rows))

    def test_b03_route_binding_uses_the_actual_routes_collection(self):
        t,s=fixture();n=normalize(t,s)
        self.assertNotIn('action_link_unresolved',[x['kind'] for x in n['issues']])

    def test_b08_publish_is_pending_and_reports_escape_configuration_markup(self):
        import catalog_store,tempfile
        from test_interface_sources import raw_capture
        r,s,m=raw_capture();r['tables']['mode_pageexpand'][0]['expendname']='<script>fixture()</script>'
        with tempfile.TemporaryDirectory() as td:
            p=catalog_store.publish(Path(td),'fixture',r,s,{k:'synthetic' for k in m['dependencies']})
            self.assertTrue((p/'B08接口与字段衔接.html').exists())
            self.assertTrue((p/'B08流程_10.html').exists())
            self.assertTrue((p/'动作注册.csv').exists())
            for h in p.glob('*.html'):self.assertNotIn('<script>',h.read_text('utf-8'))
            with self.assertRaises(ValueError):catalog_store.selected_batch(Path(td),'fixture','B08')

    def test_dml_sql_source_inherits_the_parent_data_source_context(self):
        t,s=fixture();t['formactionset'][0]['datasourceid']='external_pool'
        t['formactionsqlset'][0]['dmlsql']='update target set code=s.code from remote_source s'
        n=normalize(t,s);r=next(x for x in n['sql_source_candidates'] if x['source']=='formactionsqlset')
        self.assertFalse(r['local_database_candidate']);self.assertEqual(r['datasource_context_reference']['source'],'formactionset')
    def test_orphan_dml_sql_does_not_claim_a_known_local_data_source(self):
        t,s=fixture();t['formactionsqlset'][0]['actionid']=999;t['formactionsqlset'][0]['dmlsql']='select * from unknown_source'
        r=normalize(t,s)['sql_source_candidates'][0];self.assertFalse(r['local_database_candidate'])

    def test_shared_parent_details_are_accessible_in_html_and_csv(self):
        from catalog_reports import report
        t,s=fixture();t['mode_pageexpanddetail'].append({'id':21,'mainid':2,'interfacetype':1,'name':'SYNTHETIC_PARENT_DETAIL'})
        n=normalize(t,s)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);report(p,{'started_at':'2026-11-11T01:00:00+00:00','ended_at':'2026-11-11T01:00:01+00:00'},n,{'status':'baseline'})
            self.assertTrue((p/'B08扩展_2.html').exists())
            self.assertIn('SYNTHETIC_PARENT_DETAIL',(p/'B08扩展_2.html').read_text('utf-8'))
            self.assertIn('SYNTHETIC_PARENT_DETAIL',(p/'模块扩展.csv').read_text('utf-8-sig'))

    def test_unselected_target_rows_are_preserved_without_claiming_a_mapping(self):
        t,s=fixture();t['mode_triggerworkflowsetdetail'][0].update(modefieldid=999,wffieldid=0)
        n=normalize(t,s);m=n['workflow_triggers'][0]['mappings'][0]
        self.assertEqual(m['mapping_state'],'target_unselected');self.assertIsNone(m['model_field_reference'])
        self.assertEqual(m['workflow_field_reference']['namespace'],'not_selected')
        self.assertEqual(m['configuration']['modefieldid'],999)
        self.assertNotIn('interface_field_unresolved',[x['kind'] for x in n['issues']])
    def test_negative_no_position_sentinel_is_not_a_missing_static_node_or_route(self):
        t,s=fixture();t['workflowactionset'][0].update(nodeid=-1,nodelinkid=-1)
        n=normalize(t,s);kinds=[x['kind'] for x in n['issues']]
        self.assertNotIn('action_node_unresolved',kinds);self.assertNotIn('action_link_unresolved',kinds)
