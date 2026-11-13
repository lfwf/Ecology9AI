import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_b02 import fixture as b02_fixture
def fixture():
    from categories.b02 import normalize
    raw,seed=b02_fixture();raw['workflow_billfield'][0]['fielddbtype']='browser.master'
    seed['B02']=normalize(raw,seed)
    tables={name:list(rows) for name,rows in raw.items()}
    for name,rows in raw.items():
        if not name.startswith('physical_'):tables['B02_'+name]=list(rows)
    for name in ['workflow_datainput_entry','workflow_datainput_main','workflow_datainput_table','workflow_datainput_field','workflow_addinoperate']:tables['B05_'+name]=[]
    tables['workflow_bill'].append(dict(id=-9,namelabel=-30,tablename='uf_master',detailtablename=None,detailkeyfield=None))
    tables['Workflow_billdetailtable'].append(dict(id=3,billid=-9,tablename='uf_master_dt1',orderid=1,title='明细'))
    tables['workflow_billfield']+= [
        dict(id=201,billid=-9,fieldname='code',fieldlabel=-31,fielddbtype='varchar(20)',fieldhtmltype='1',type=1,viewtype=0,detailtable=None),
        dict(id=202,billid=-9,fieldname='code',fieldlabel=-32,fielddbtype='varchar(20)',fieldhtmltype='1',type=1,viewtype=1,detailtable='uf_master_dt1')]
    tables['HtmlLabelInfo']+=[dict(indexid=-30,languageid=7,labelname='测试主数据'),dict(indexid=-31,languageid=7,labelname='主编码'),dict(indexid=-32,languageid=7,labelname='明细编码')]
    for table in ['uf_master','uf_master_dt1']:
        for i,(column,typ) in enumerate([('id','int'),('code','varchar')]+([('mainid','int')] if table.endswith('dt1') else [])):
            tables['physical_columns'].append(dict(schema_name='dbo',table_name=table,column_id=i+1,column_name=column,data_type=typ,max_length=20 if typ=='varchar' else 4,precision=10,scale=0,is_nullable=True))
        tables['physical_keys'].append(dict(schema_name='dbo',table_name=table,index_name='PK_'+table,column_name='id',key_ordinal=1,is_unique=True,is_primary_key=True,has_filter=False,is_disabled=False,is_hypothetical=False))
    tables['MODE_BROWSER']=[dict(id=1,showname='master',customid=2,datasourceid=None,sqltext=None,keyfield='code',showfield='code')]
    tables['datashowset']=[]
    tables['mode_custombrowser']=[dict(id=2,modeid=8,formid=-9,customname='主数据选择',detailtable=None,defaultsql='')]
    tables['mode_CustombrowserDspField']=[dict(id=30,customid=2,fieldid=201,ispk=1,isshow='1',istitle=1)]
    tables['modeinfo']=[dict(id=8,modename='测试模块',formid=-9,subcompanyid=0,isdelete=0)]
    for name in ['mode_workflowtomodeset','mode_workflowtomodesetdetail','mode_workflowtomodesetopt','HrmSubCompany']:tables[name]=[]
    seed['_source_database']='fixture'
    return tables,seed
class B06Tests(unittest.TestCase):
    def setUp(self):
        from categories.b06 import normalize
        self.normalize=normalize
    def test_model_form_is_not_invented_as_workflow(self):
        t,s=fixture();d=self.normalize(t,s);form=next(f for f in d['dictionary']['forms'] if f['form_id']==-9)
        self.assertEqual(form['workflow_ids'],[]);self.assertEqual(d['models'][0]['form_reference']['form_id'],-9)
        self.assertEqual(d['workflow_links'][0]['reachable_model_ids'],[8])
    def test_detail_browser_returns_detail_field_not_same_named_main_column(self):
        t,s=fixture();t['mode_custombrowser'][0]['detailtable']='uf_master_dt1';t['mode_CustombrowserDspField'][0]['fieldid']=202
        custom=self.normalize(t,s)['browsers'][0]['registrations'][0]['custom_browser']
        self.assertEqual(custom['return_keys'][0]['field_reference']['physical_table'],'uf_master_dt1')
        self.assertEqual(custom['grain_reference']['table_name'],'uf_master_dt1')
    def test_missing_browser_definition_is_retained(self):
        t,s=fixture();t['MODE_BROWSER']=[]
        b=self.normalize(t,s)['browsers'][0]
        self.assertEqual(b['code'],'master');self.assertEqual(b['lookup_state'],'missing_in_visible_registries')
    def test_modern_and_legacy_same_name_are_separate_candidates(self):
        t,s=fixture();t['datashowset']=[dict(id=1,showname='master',customid=2,datasourceid=None)]
        b=self.normalize(t,s)['browsers'][0]
        self.assertEqual({r['source'] for r in b['registrations']},{'MODE_BROWSER','datashowset'})
        self.assertEqual(b['lookup_state'],'multiple_registrations_pending_priority')
    def test_browser_internal_negative_field_is_not_workflow_title(self):
        t,s=fixture();t['mode_CustombrowserDspField'][0]['fieldid']=-1
        ref=self.normalize(t,s)['browsers'][0]['registrations'][0]['custom_browser']['return_keys'][0]['field_reference']
        self.assertEqual(ref['namespace'],'browser_internal');self.assertNotEqual(ref.get('name'),'流程标题')
    def test_model_form_sign_is_preserved(self):
        t,s=fixture();t['mode_custombrowser'][0]['formid']=9
        d=self.normalize(t,s);custom=d['browsers'][0]['registrations'][0]['custom_browser']
        self.assertIsNone(custom['form_reference'])
        self.assertIn('custom_browser_form_unresolved',{i['kind'] for i in d['issues']})
    def test_ambiguous_unqualified_schema_is_not_chosen(self):
        t,s=fixture();extra=[dict(r,schema_name='shadow') for r in t['physical_columns'] if r['table_name']=='uf_master'];t['physical_columns']+=extra
        d=self.normalize(t,s);f=next(f for f in d['dictionary']['fields'] if f['form_id']==-9 and f['field_id']==201)
        self.assertIsNone(f['physical_column']);self.assertIn('physical_schema_ambiguous',{i['kind'] for i in d['issues']})
    def test_external_sql_source_is_not_bound_to_same_named_local_table(self):
        t,s=fixture();t['MODE_BROWSER'][0].update(datasourceid='external_point',sqltext='SELECT code FROM other.dbo.uf_master')
        refs=self.normalize(t,s)['sql_source_candidates']
        self.assertTrue(refs);self.assertTrue(all(not r['local_database_candidate'] for r in refs))
    def test_source_mapping_uses_workflow_namespace_and_target_model_form(self):
        t,s=fixture();s['workflows'].append(dict(id=20,name='旧流程',form_id=14,isbill_raw='0',form_source='workflow_formbase'))
        s['B02']['fields'].append(dict(form_source='workflow_formbase',form_id=14,field_id=201,name='来源字段',column_name='legacy_code',physical_table='workflow_form'))
        t['mode_workflowtomodeset']=[dict(id=40,workflowid=20,modeid=8,isenable='1')]
        t['mode_workflowtomodesetdetail']=[dict(id=41,mainid=40,modefieldid=201,wffieldid=201,defaultvalue='0')]
        setting=self.normalize(t,s)['workflow_model_settings'][0]
        mapping=setting['mappings'][0]
        self.assertEqual(mapping['workflow_field_reference']['column_name'],'legacy_code')
        self.assertEqual(mapping['model_field_reference']['physical_table'],'uf_master')
        self.assertEqual(mapping['configuration']['defaultvalue'],'0')
    def test_cycles_in_master_references_do_not_duplicate_reachable_models(self):
        t,s=fixture();t['workflow_billfield'][-2]['fielddbtype']='browser.master'
        d=self.normalize(t,s);self.assertEqual(d['workflow_links'][0]['reachable_model_ids'],[8])
        self.assertFalse(d['runtime_verified'])
    def test_raw_sources_have_explicit_representation_and_anchors_are_labelled(self):
        t,s=fixture();d=self.normalize(t,s)
        self.assertTrue(all(c['raw_records']==c['represented_records'] for c in d['source_coverage'].values()))
        self.assertEqual(d['source_coverage']['B02_workflow_bill']['role'],'dependency_validation')
    def test_composite_unique_index_does_not_prove_browser_key_unique(self):
        t,s=fixture()
        for ordinal,col in enumerate(['code','id'],1):t['physical_keys'].append(dict(schema_name='dbo',table_name='uf_master',index_name='U_code_id',column_name=col,key_ordinal=ordinal,is_unique=True,is_primary_key=False,has_filter=False,is_disabled=False,is_hypothetical=False))
        key=self.normalize(t,s)['browsers'][0]['registrations'][0]['custom_browser']['return_keys'][0]
        self.assertEqual(key['physical_key_state'],'not_proven_unique')
    def test_legacy_workflow_options_and_browser_definitions_are_kept(self):
        t,s=fixture();s['workflows'].append(dict(id=20,name='旧流程',form_id=14,isbill_raw='0',form_source='workflow_formbase'))
        t['B02_workflow_formbase']=[dict(id=14,formname='旧表单')]
        t['B02_workflow_formfield']=[dict(formid=14,fieldid=101,isdetail=None,groupId=None),dict(formid=14,fieldid=102,isdetail=None,groupId=None)]
        t['B02_workflow_formdict']=[dict(id=101,fieldname='old_choice',fielddbtype='varchar(20)',fieldhtmltype='5',type=1),dict(id=102,fieldname='old_browser',fielddbtype='int',fieldhtmltype='3',type=999)]
        t['B02_workflow_fieldlable']=[dict(formid=14,fieldid=101,langurageid=7,fieldlable='旧选项'),dict(formid=14,fieldid=102,langurageid=7,fieldlable='旧浏览')]
        t['B02_workflow_SelectItem']=[dict(id=701,isbill=0,fieldid=101,selectvalue='0',selectname='旧值')]
        t['B02_workflow_browserurl']=[dict(id=999,tablename='hrm_fixture',keycolumname='id',columname='name')]
        d=self.normalize(t,s)
        fields={f['field_id']:f for f in d['dictionary']['fields'] if f['form_source']=='workflow_formbase' and f['form_id']==14}
        self.assertEqual(fields[101]['options'][0]['selectvalue'],'0')
        self.assertEqual(fields[102]['browser_definition']['id'],999)

    def test_action_reference_supplies_explicit_candidate_workflow_for_global_setting(self):
        t,s=fixture();t['mode_workflowtomodeset']=[dict(id=40,workflowid=0,modeid=8)]
        t['mode_workflowtomodesetdetail']=[dict(id=41,mainid=40,modefieldid=201,wffieldid=101,defaultvalue='0')]
        t['B05_workflow_addinoperate']=[dict(id=50,workflowid=10,wftomodesetid='40')]
        d=self.normalize(t,s);setting=d['workflow_model_settings'][0]
        self.assertEqual(setting['workflow_reference_basis'],'unique_action_reference_candidate')
        self.assertEqual(setting['mappings'][0]['workflow_field_reference']['column_name'],'amount')
        self.assertEqual(d['workflow_links'][0]['reachable_model_ids'],[8])

if __name__=='__main__':unittest.main()
