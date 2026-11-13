import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def fixture():
    tables={
      'workflow_bill':[{'id':-7,'namelabel':10,'tablename':'formtable_main_7','detailtablename':None,'detailkeyfield':None}],
      'Workflow_billdetailtable':[{'id':1,'billid':-7,'tablename':'formtable_main_7_dt1','title':'明细一','orderid':1},
                                  {'id':2,'billid':-7,'tablename':'formtable_main_7_dt2','title':'明细二','orderid':2}],
      'workflow_billfield':[{'id':101,'billid':-7,'fieldname':'amount','fieldlabel':20,'fielddbtype':'decimal(18,2)','fieldhtmltype':'1','type':1,'viewtype':0,'detailtable':None},
                            {'id':102,'billid':-7,'fieldname':'amount','fieldlabel':21,'fielddbtype':'decimal(18,2)','fieldhtmltype':'1','type':1,'viewtype':1,'detailtable':'formtable_main_7_dt1'},
                            {'id':103,'billid':-7,'fieldname':'amount','fieldlabel':22,'fielddbtype':'decimal(18,2)','fieldhtmltype':'1','type':1,'viewtype':1,'detailtable':'formtable_main_7_dt2'}],
      'HtmlLabelInfo':[{'indexid':10,'languageid':7,'labelname':'申请单'},
                       {'indexid':20,'languageid':7,'labelname':'总金额'},
                       {'indexid':21,'languageid':7,'labelname':'行金额一'},
                       {'indexid':22,'languageid':7,'labelname':'行金额二'}],
      'workflow_SelectItem':[], 'workflow_browserurl':[], 'workflow_browsertype':[],
      'workflow_formbase':[], 'workflow_formfield':[], 'workflow_formdict':[],
      'workflow_formdictdetail':[], 'workflow_fieldlable':[],
      'physical_columns':[], 'physical_keys':[], 'physical_foreign_keys':[]
    }
    for name in ['formtable_main_7','formtable_main_7_dt1','formtable_main_7_dt2']:
        for i,(col,typ) in enumerate([('id','int'),('amount','decimal')]+([] if name=='formtable_main_7' else [('mainid','int')])):
            tables['physical_columns'].append(dict(table_name=name,column_name=col,data_type=typ,column_id=i+1,max_length=8,precision=18,scale=2,is_nullable=True))
        tables['physical_keys'].append(dict(table_name=name,index_name='PK_'+name,is_primary_key=True,is_unique=True,has_filter=False,is_disabled=False,is_hypothetical=False,key_ordinal=1,column_name='id'))
    seed={'workflows':[dict(id=10,name='测试申请',form_id=-7,isbill_raw='1',form_source='workflow_bill')]}
    return tables,seed

class B02Tests(unittest.TestCase):
    def setUp(self):
        from categories.b02 import normalize
        self.normalize=normalize

    def test_two_details_and_duplicate_field_names_remain_separate(self):
        tables,seed=fixture(); doc=self.normalize(tables,seed)
        self.assertEqual(len(doc['forms']),1)
        self.assertEqual(len(doc['forms'][0]['details']),2)
        self.assertEqual(len(doc['fields']),3)
        self.assertEqual(len({f['physical_table'] for f in doc['fields']}),3)
        self.assertEqual({f['name'] for f in doc['fields']},{'总金额','行金额一','行金额二'})
        self.assertEqual(doc['forms'][0]['form_id'],-7)

    def test_detail_relationship_is_structural_not_runtime_verified(self):
        tables,seed=fixture(); doc=self.normalize(tables,seed)
        relation=doc['relationships'][0]
        self.assertEqual(relation['child_column'],'mainid')
        self.assertEqual(relation['parent_column'],'id')
        self.assertFalse(relation['runtime_verified'])
        self.assertFalse(relation['database_fk_enforced'])
        self.assertEqual(relation['parent_key_state'],'unique_single_column')
        self.assertTrue(doc['aggregation_rules'])

    def test_composite_unique_index_does_not_prove_unique_id(self):
        tables,seed=fixture()
        tables['physical_keys'].append(dict(table_name='formtable_main_7',index_name='PK_formtable_main_7',is_primary_key=True,is_unique=True,has_filter=False,is_disabled=False,is_hypothetical=False,key_ordinal=2,column_name='amount'))
        doc=self.normalize(tables,seed)
        self.assertEqual(doc['relationships'][0]['parent_key_state'],'not_proven_unique')

    def test_missing_physical_column_is_visible(self):
        tables,seed=fixture()
        tables['physical_columns']=[c for c in tables['physical_columns'] if not(c['table_name']=='formtable_main_7_dt2' and c['column_name']=='amount')]
        doc=self.normalize(tables,seed)
        self.assertIn('configured_column_not_found',{i['kind'] for i in doc['issues']})

    def test_ambiguous_label_is_not_arbitrarily_chosen(self):
        tables,seed=fixture()
        tables['HtmlLabelInfo'].append({'indexid':20,'languageid':7,'labelname':'冲突标签'})
        doc=self.normalize(tables,seed)
        self.assertEqual(doc['fields'][0]['label_state'],'ambiguous')
        self.assertIn('label_ambiguous',{i['kind'] for i in doc['issues']})

    def test_unknown_detail_does_not_fall_back_to_main(self):
        tables,seed=fixture(); tables['workflow_billfield'][1]['detailtable']='missing_detail'
        doc=self.normalize(tables,seed)
        field=next(f for f in doc['fields'] if f['field_id']==102)
        self.assertEqual(field['physical_table'],'missing_detail')
        self.assertIn('detail_not_registered',{i['kind'] for i in doc['issues']})

    def test_option_namespace_prevents_cross_form_kind_collision(self):
        tables,seed=fixture()
        tables['workflow_SelectItem']=[dict(id=1,fieldid=101,isbill=0,selectvalue=0,selectname='旧表选项'),
                                       dict(id=2,fieldid=101,isbill=1,selectvalue=1,selectname='本表选项')]
        doc=self.normalize(tables,seed)
        field=next(f for f in doc['fields'] if f['field_id']==101)
        self.assertEqual([o['selectname'] for o in field['options']],['本表选项'])

    def test_old_form_field_uses_own_label_and_shared_physical_table(self):
        tables,seed=fixture()
        seed['workflows'].append(dict(id=11,name='旧流程',form_id=14,isbill_raw='0',form_source='workflow_formbase'))
        tables['workflow_formbase']=[dict(id=14,formname='旧式表单')]
        tables['workflow_formfield']=[dict(formid=14,fieldid=101,isdetail='0',groupId=0)]
        tables['workflow_formdict']=[dict(id=101,fieldname='subject',fielddbtype='varchar(100)',fieldhtmltype='1',type=1)]
        tables['workflow_fieldlable']=[dict(formid=14,fieldid=101,fieldlable='事由',langurageid=7)]
        tables['physical_columns'].append(dict(table_name='workflow_form',column_name='subject',data_type='varchar',column_id=1,max_length=100,precision=0,scale=0,is_nullable=True))
        doc=self.normalize(tables,seed)
        old=next(f for f in doc['fields'] if f['form_source']=='workflow_formbase')
        self.assertEqual(old['name'],'事由')
        self.assertEqual(old['physical_table'],'workflow_form')
        bill=next(f for f in doc['fields'] if f['form_source']=='workflow_bill' and f['field_id']==101)
        self.assertNotEqual(old['field_key'],bill['field_key'])

    def test_null_old_detail_flag_preserves_dictionary_field(self):
        tables,seed=fixture()
        seed['workflows']=[dict(id=11,name='旧流程',form_id=14,isbill_raw='0',form_source='workflow_formbase')]
        tables['workflow_formbase']=[dict(id=14,formname='旧式表单')]
        tables['workflow_formfield']=[dict(formid=14,fieldid=9,isdetail=None,groupId=0)]
        tables['workflow_formdict']=[dict(id=9,fieldname='subject',fielddbtype='varchar(100)',fieldhtmltype='1',type=1)]
        doc=self.normalize(tables,seed)
        self.assertEqual(len(doc['fields']),1)
        self.assertEqual(doc['fields'][0]['physical_table'],'workflow_form')
        self.assertIn('old_null_detail_flag',{i['kind'] for i in doc['issues']})

    def test_custom_browser_descriptor_is_not_sql_type(self):
        tables,seed=fixture()
        tables['workflow_billfield'][0].update(fielddbtype='browser.fixture',fieldhtmltype='3',type=161)
        doc=self.normalize(tables,seed)
        field=next(f for f in doc['fields'] if f['field_id']==101)
        self.assertEqual(field['custom_browser_code'],'fixture')
        self.assertNotIn('declared_type_unparsed',{i['kind'] for i in doc['issues']})

    def test_explicit_detail_key_is_not_overridden_by_mainid(self):
        tables,seed=fixture()
        tables['workflow_bill'][0]['detailkeyfield']='ownerid'
        for name in ['formtable_main_7_dt1','formtable_main_7_dt2']:
            tables['physical_columns'].append(dict(table_name=name,column_name='ownerid',data_type='int',column_id=8,max_length=4,precision=10,scale=0,is_nullable=True))
        doc=self.normalize(tables,seed)
        self.assertEqual({r['child_column'] for r in doc['relationships']},{'ownerid'})

    def test_disabled_unique_index_does_not_prove_uniqueness(self):
        tables,seed=fixture()
        for row in tables['physical_keys']:
            if row['table_name']=='formtable_main_7':row['is_disabled']=True
        doc=self.normalize(tables,seed)
        self.assertEqual(doc['relationships'][0]['parent_key_state'],'not_proven_unique')

    def test_composite_fk_component_is_not_single_column_enforcement(self):
        tables,seed=fixture()
        tables['physical_foreign_keys']=[
            dict(constraint_name='FK_composite',child_table='formtable_main_7_dt1',child_column='mainid',parent_table='formtable_main_7',parent_column='id',constraint_column_id=1,is_disabled=False,is_not_trusted=False),
            dict(constraint_name='FK_composite',child_table='formtable_main_7_dt1',child_column='other_nullable',parent_table='formtable_main_7',parent_column='other',constraint_column_id=2,is_disabled=False,is_not_trusted=False)]
        doc=self.normalize(tables,seed)
        self.assertFalse(doc['relationships'][0]['database_fk_enforced'])

    def test_type_size_difference_and_actual_sql_type_are_explicit(self):
        tables,seed=fixture()
        tables['workflow_billfield'][0]['fielddbtype']='decimal(12,2)'
        doc=self.normalize(tables,seed)
        field=next(f for f in doc['fields'] if f['field_id']==101)
        self.assertEqual(field['physical_sql_type'],'decimal(18,2)')
        self.assertIn('field_size_mismatch',{i['kind'] for i in doc['issues']})

if __name__=='__main__':unittest.main()
