import sys,copy,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def fixture():
    names=[('workflow_requestbase','USER_TABLE'),('workflow_currentoperator','USER_TABLE'),('V_JDSX','VIEW'),('workflow_requestLog','USER_TABLE'),('workflow_base','USER_TABLE')]
    t={'objects':[dict(schema_name='dbo',object_name=n,object_id=i+1,type_desc=kind,can_select=1,can_view_definition=0) for i,(n,kind) in enumerate(names)],
       'columns':[],'indexes':[],'foreign_keys':[],'view_definitions':[dict(schema_name='dbo',object_name='V_JDSX',definition=None)],'extended_properties':[],
       'local_reference_files':[dict(reference_key='page',available=True,path='synthetic/RequestView.jsp',sha256='synthetic',evidence_state='local_reference_only_not_loaded',
                                   topics=[dict(object_name='workflow_currentoperator',columns=['isremark','islasttimes'],note='本机页面使用多个组合条件，不是完整枚举')],
                                   snippets=[dict(line=2,text="isremark='0' AND islasttimes=1")])]}
    cols={'workflow_requestbase':['requestid','workflowid','currentnodeid','currentnodetype','createdate','createtime'],
          'workflow_currentoperator':['id','requestid','workflowid','nodeid','isremark','islasttimes'],
          'V_JDSX':['rn','requestid','nodeid'],'workflow_requestLog':['LOGID','requestid','nodeid','logtype'],'workflow_base':['id']}
    for obj,fields in cols.items():
        for i,name in enumerate(fields):
            dtype='char' if name in ['currentnodetype','createdate','createtime','logtype'] else 'int'
            t['columns'].append(dict(schema_name='dbo',object_name=obj,column_id=i+1,column_name=name,data_type=dtype,max_length=10 if dtype=='char' else 4,precision=10,scale=0,is_nullable=False,is_identity=name=='LOGID',is_computed=False))
    seed={'workflows':[dict(id=10,name='流程甲',form_id=-7,form_source='workflow_bill',isbill_raw='1')]}
    return t,seed
def index(obj,columns,**flags):
    base=dict(schema_name='dbo',object_name=obj,index_id=1,index_name='ix_synthetic',is_unique=True,is_primary_key=False,is_unique_constraint=False,is_disabled=False,is_hypothetical=False,has_filter=False,filter_definition=None)
    base.update(flags)
    return [dict(base,key_ordinal=i+1,is_included_column=False,column_name=x) for i,x in enumerate(columns)]
def normalize(t,s):
    from categories import b09
    return b09.normalize(t,s)
def relation(n,source='workflow_currentoperator',target='workflow_requestbase',column='requestid'):
    return next(x for x in n['relationships'] if x['source_object']==source and x['target_object']==target and x['source_columns']==[column])
class B09Tests(unittest.TestCase):
    def test_selectable_view_with_null_definition_is_not_empty_or_known_history(self):
        t,s=fixture();n=normalize(t,s);view=next(x for x in n['objects'] if x['object_name']=='V_JDSX')
        self.assertEqual(view['definition_state'],'not_visible')
        self.assertFalse(view['grain_verified']);self.assertIsNone(view['definition'])
        self.assertEqual(relation(n,'V_JDSX')['state'],'view_definition_required')
    def test_same_name_multiple_schemas_are_preserved_without_choosing_dbo(self):
        t,s=fixture();t['objects'].append(dict(t['objects'][0],schema_name='audit',object_id=99))
        t['columns'] += [dict(x,schema_name='audit') for x in list(t['columns']) if x['object_name']=='workflow_requestbase']
        n=normalize(t,s);self.assertEqual(relation(n)['state'],'schema_ambiguous')
        self.assertEqual(len([o for o in n['objects'] if o['object_name']=='workflow_requestbase']),2)
    def test_composite_unique_does_not_prove_unique_request_id(self):
        t,s=fixture();t['indexes']=index('workflow_requestbase',['requestid','workflowid'])
        self.assertFalse(relation(normalize(t,s))['parent_unique_key_proven'])
    def test_included_column_is_not_a_key_part(self):
        t,s=fixture();t['indexes']=index('workflow_requestbase',['requestid'])
        t['indexes'].append(dict(t['indexes'][0],column_name='workflowid',key_ordinal=0,is_included_column=True))
        self.assertTrue(relation(normalize(t,s))['parent_unique_key_proven'])
    def test_filtered_disabled_or_unknown_index_never_proves_global_uniqueness(self):
        for flags in [dict(has_filter=True),dict(is_disabled=True),dict(is_hypothetical=True),dict(is_disabled=None)]:
            t,s=fixture();t['indexes']=index('workflow_requestbase',['requestid'],**flags)
            self.assertFalse(relation(normalize(t,s))['parent_unique_key_proven'],flags)
    def test_partial_composite_foreign_key_is_not_complete_join_proof(self):
        t,s=fixture();base=dict(schema_name='dbo',object_name='workflow_currentoperator',foreign_key_name='fk_pair',referenced_schema='dbo',referenced_object='workflow_requestbase',is_disabled=False,is_not_trusted=False)
        t['foreign_keys']=[dict(base,constraint_column_id=1,column_name='requestid',referenced_column='requestid'),dict(base,constraint_column_id=2,column_name='nodeid',referenced_column='currentnodeid')]
        self.assertFalse(relation(normalize(t,s))['foreign_key_enforced'])
    def test_identity_or_column_name_does_not_prove_primary_key_or_node_round(self):
        t,s=fixture();n=normalize(t,s)
        self.assertFalse(n['node_rounds_reconstructible'])
        event=next(o for o in n['objects'] if o['object_name']=='workflow_requestLog')
        self.assertEqual(event['unique_keys'],[])
    def test_status_semantics_are_per_object_and_reference_is_not_complete_enum(self):
        t,s=fixture();n=normalize(t,s)
        op=next(x for x in n['state_fields'] if x['object_name']=='workflow_currentoperator' and x['column_name']=='isremark')
        log=next(x for x in n['state_fields'] if x['object_name']=='workflow_requestLog' and x['column_name']=='logtype')
        self.assertTrue(op['local_references']);self.assertFalse(op['complete_enumeration']);self.assertFalse(log['local_references'])
        self.assertFalse(op['business_values_observed']);self.assertIsNone(op['confirmed_code_dictionary'])
    def test_char_date_and_time_are_not_converted_to_utc(self):
        t,s=fixture();n=normalize(t,s)
        d=next(x for x in n['time_fields'] if x['column_name']=='createdate' and x['object_name']=='workflow_requestbase')
        self.assertEqual(d['storage_class'],'string_without_verified_format_or_timezone')
        self.assertFalse(d['timezone_verified'])
    def test_missing_object_is_not_called_nonexistent_and_coverage_is_exact(self):
        t,s=fixture();n=normalize(t,s)
        m=next(x for x in n['objects'] if x['object_name']=='CubeInterfaceLog')
        self.assertEqual(m['visibility_state'],'not_visible')
        for name,rows in t.items():self.assertEqual(n['source_coverage'][name]['represented_records'],len(rows))
    def test_available_view_definition_provides_candidates_without_execution(self):
        t,s=fixture();t['objects'][2]['can_view_definition']=1;t['view_definitions'][0]['definition']="select 'from fake' as x,requestid from dbo.real_source"
        n=normalize(t,s);self.assertEqual([x['object_name'] for x in n['view_source_candidates']],['real_source'])
        self.assertFalse(n['runtime_verified'])
    def test_type_mismatch_is_visible_without_implicit_coercion(self):
        t,s=fixture()
        for c in t['columns']:
            if c['object_name']=='workflow_currentoperator' and c['column_name']=='requestid':c['data_type']='varchar'
        self.assertEqual(relation(normalize(t,s))['state'],'column_type_mismatch')
    def test_reference_markup_and_obvious_secret_are_passive(self):
        t,s=fixture();t['view_definitions'][0]['definition']="select * from dbo.real_source -- <script>x()</script>\n-- password='fixtureSecret'"
        n=normalize(t,s);self.assertNotIn('fixtureSecret',json.dumps(n))
        from catalog_reports import report
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);report(p,{'started_at':'2026-11-11T01:00:00+00:00','ended_at':'2026-11-11T01:00:01+00:00'},n,{'status':'baseline'})
            self.assertTrue((p/'B09运行记录数据结构.html').exists())
            for h in p.glob('*.html'):self.assertNotIn('<script>',h.read_text('utf-8'));self.assertNotIn('fixtureSecret',h.read_text('utf-8'))

    def test_case_variants_across_schemas_do_not_hide_visible_candidates(self):
        t,s=fixture();other='Workflow_RequestBase'
        t['objects'].append(dict(t['objects'][0],schema_name='audit',object_name=other,object_id=99))
        t['columns'] += [dict(x,schema_name='audit',object_name=other) for x in list(t['columns']) if x['object_name']=='workflow_requestbase']
        n=normalize(t,s)
        self.assertEqual(relation(n)['state'],'schema_ambiguous')
        self.assertEqual(len([o for o in n['objects'] if o['requested_name']=='workflow_requestbase']),2)
