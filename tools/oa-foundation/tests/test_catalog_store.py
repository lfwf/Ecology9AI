import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_b02 import fixture

def capture():
    tables,seed=fixture()
    raw=dict(format_version=1,category='B02',method_version='1.0.0',scope='forms_referenced_by_B01_all_states',
             started_at='2026-11-11T01:00:00+00:00',ended_at='2026-11-11T01:00:01+00:00',
             business_rows_read=0,source_identity={'server':'fixture','database':'fixture'},
             schema=[{'object_name':'workflow_bill','column_name':'id','data_type':'int'}],tables=tables,
             checks={t:dict(complete=True,row_count=len(v),hash_first='same',hash_second='same',
                            pages=[dict(offset=0,take=500,row_count=len(v))]) for t,v in tables.items()})
    return raw,seed

class StoreTests(unittest.TestCase):
    def setUp(self):
        import catalog_store
        self.store=catalog_store
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_baseline_and_compatible_update_keep_immutable_batches(self):
        raw,seed=capture()
        a=self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic'})
        original=(a/'raw.json').read_bytes()
        b=self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic'})
        self.assertNotEqual(a,b)
        self.assertEqual(original,(a/'raw.json').read_bytes())
        diff=json.loads((b/'diff.json').read_text('utf-8'))
        self.assertEqual(diff['status'],'compared')
        self.assertTrue(all(not x['added'] and not x['source_missing'] and not x['changed'] for x in diff['sources'].values()))
    def test_incomplete_or_business_source_does_not_replace_success(self):
        raw,seed=capture();a=self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic'})
        raw['tables']['workflow_requestbase']=[]
        with self.assertRaises(ValueError): self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic'})
        self.assertEqual(self.store.status(self.root,'fixture','B02')['latest_success'],a.name)
        del raw['tables']['workflow_requestbase'];raw['checks']['workflow_bill']['complete']=False
        with self.assertRaises(ValueError): self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic'})
    def test_changed_source_is_not_comparable(self):
        raw,seed=capture();self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic'})
        raw['source_identity']['database']='another'
        b=self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic'})
        self.assertEqual(json.loads((b/'diff.json').read_text('utf-8'))['status'],'not_comparable')
    def test_old_capture_is_rejected(self):
        raw,seed=capture();self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic'})
        raw.update(started_at='2026-11-10T01:00:00+00:00',ended_at='2026-11-10T01:00:01+00:00')
        with self.assertRaises(ValueError):self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic'})
    def test_review_pending_until_explicit_acceptance(self):
        raw,seed=capture();a=self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic'})
        with self.assertRaises(ValueError):self.store.selected_batch(self.root,'fixture','B02')
        self.store.review(self.root,'fixture','B02',a.name,'tester','accepted','仅确认合成范围','partial')
        self.assertEqual(self.store.selected_batch(self.root,'fixture','B02').name,a.name)
    def test_duplicate_source_keys_do_not_silently_drop_records(self):
        before=[dict(id=1,name='a'),dict(id=1,name='b')]
        result=self.store.diff_rows(before,[dict(id=1,name='a')],['id'])
        self.assertEqual(result['status'],'ambiguous_keys_multiset')
        self.assertEqual(len(result['source_missing']),1)

    def test_b04_cli_selects_master_report_with_multiple_html_files(self):
        import subprocess
        from test_b04 import fixture as b04_fixture
        tables,seed=b04_fixture();raw,_=capture();raw.update(category='B04',scope=self.store.method('B04')['scope'],tables=tables,
            checks={t:dict(complete=True,row_count=len(v),hash_first='same',hash_second='same',pages=[dict(offset=0,take=500,row_count=len(v))]) for t,v in tables.items()})
        batch=self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic','B02':'synthetic','B03':'synthetic'})
        script=Path(__file__).resolve().parents[1]/'run.py'
        result=subprocess.run([sys.executable,str(script),'--data-root',str(self.root),'--environment','fixture','--category','B04','show','--unreviewed'],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        self.assertEqual(Path(data['report']).name,'B04审核人与字段权限.html')

    def test_missing_declared_dependency_cannot_publish(self):
        raw,seed=capture()
        with self.assertRaises(ValueError):self.store.publish(self.root,'fixture',raw,seed,{})

    def test_b05_publishes_reports_and_hashes_reused_analyzer(self):
        import hashlib
        from test_b05 import fixture as b05_fixture
        tables,seed=b05_fixture();raw,_=capture();raw.update(category='B05',scope=self.store.method('B05')['scope'],tables=tables,
            checks={t:dict(complete=True,row_count=len(v),hash_first='same',hash_second='same',pages=[dict(offset=0,take=500,row_count=len(v))]) for t,v in tables.items()})
        batch=self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic','B02':'synthetic','B03':'synthetic'})
        manifest=json.loads((batch/'manifest.json').read_text('utf-8'))
        support=manifest['compatibility']['normalizer_support_code']
        source=Path(__file__).resolve().parents[2]/'oa-workflow-analyzer/src/oa_workflow_analyzer/scripts.py'
        self.assertIn(hashlib.sha256(source.read_bytes()).hexdigest(),support.values())
        self.assertTrue((batch/'B05自动处理配置.html').is_file())
        self.assertTrue((batch/'B05流程_10.html').is_file())
        self.assertTrue((batch/'数据带入映射.csv').is_file())

    def test_b06_publish_requires_closed_graph_and_keeps_failed_pointer(self):
        from test_b06 import fixture as b06_fixture
        tables,seed=b06_fixture()
        tables['MODE_BROWSER'][0]['sqltext']="SELECT * FROM uf_master; password='SYNTHETIC_SECRET'; -- <script>alert(1)</script>"
        tables['MODE_BROWSER'][0]['showpageurl']='https://demo:SYNTHETIC_URL_PASS@example.invalid/?client_secret=SYNTHETIC_QUERY_SECRET'
        method=self.store.method('B06');allowed=set(method['sources'])|set(method['metadata_sources'])
        tables={name:tables.get(name,[]) for name in allowed}
        raw,_=capture();raw.update(category='B06',method_version='1.0.0',scope=method['scope'],tables=tables,reference_graph=dict(closed=True,iterations=[dict(iteration=0)]),
            checks={name:dict(complete=True,row_count=len(v),hash_first='same',hash_second='same',pages=[] if name in method['metadata_sources'] else [dict(row_count=len(v))]) for name,v in tables.items()})
        batch=self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic','B02':'synthetic','B05':'synthetic'})
        self.assertTrue((batch/'B06关联建模与浏览框.html').is_file())
        self.assertTrue((batch/'模块字段.csv').is_file())
        for output in list(batch.glob('*.html'))+list(batch.glob('*.csv'))+[batch/'normalized.json']:
            body=output.read_text('utf-8-sig')
            if output.suffix=='.html':self.assertTrue('<script>' not in body,output.name)
            for secret in ['SYNTHETIC_SECRET','SYNTHETIC_URL_PASS','SYNTHETIC_QUERY_SECRET']:self.assertTrue(secret not in body,output.name)
        self.assertIn('&lt;script&gt;', (batch/'B06关联建模与浏览框.html').read_text('utf-8'))

        raw['reference_graph']['closed']=False
        with self.assertRaises(ValueError):self.store.publish(self.root,'fixture',raw,seed,{'B01':'synthetic','B02':'synthetic','B05':'synthetic'})
        self.assertEqual(self.store.status(self.root,'fixture','B06')['latest_success'],batch.name)

    def test_b06_report_does_not_attach_bill_model_to_same_number_legacy_form(self):
        import csv
        from test_b06 import fixture as b06_fixture
        from catalog_reports import report_b06
        from categories.b06 import normalize
        tables,seed=b06_fixture();tables['workflow_bill'][-1]['id']=14;tables['modeinfo'][0]['formid']=14;tables['mode_custombrowser'][0]['formid']=14
        for row in tables['workflow_billfield']:
            if row['billid']==-9:row['billid']=14
        for row in tables['Workflow_billdetailtable']:
            if row['billid']==-9:row['billid']=14
        seed['workflows'].append(dict(id=20,name='旧流程',form_id=14,isbill_raw='0',form_source='workflow_formbase'))
        tables['B02_workflow_formbase']=[dict(id=14,formname='旧表单')]
        tables['B02_workflow_formfield']=[dict(formid=14,fieldid=901,isdetail=None,groupId=None)]
        tables['B02_workflow_formdict']=[dict(id=901,fieldname='old',fielddbtype='int',fieldhtmltype='1',type=1)]
        tables['B02_workflow_fieldlable']=[dict(formid=14,fieldid=901,langurageid=7,fieldlable='旧字段')]
        doc=normalize(tables,seed);raw,_=capture()
        folder=self.root/'report';folder.mkdir();report_b06(folder,raw,doc,dict(status='baseline'))
        with (folder/'模块字段.csv').open(encoding='utf-8-sig',newline='') as h:rows=list(csv.DictReader(h))
        legacy=[r for r in rows if r['表单来源']=='workflow_formbase' and r['表单ID']=='14']
        self.assertTrue(legacy);self.assertEqual(legacy[0]['模块ID'],'')
        bill=[r for r in rows if r['表单来源']=='workflow_bill' and r['表单ID']=='14']
        self.assertTrue(bill);self.assertEqual(bill[0]['模块ID'],'8')

if __name__=='__main__':unittest.main()
