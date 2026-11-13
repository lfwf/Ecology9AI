import sys,unittest,json,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def fixture():
    seed={'workflows':[{'id':1,'name':'流程甲','form_id':-14,'form_source':'workflow_bill','isbill_raw':'1'},
                       {'id':2,'name':'流程乙','form_id':14,'form_source':'workflow_formbase','isbill_raw':'0'}],
          'B06':{'dictionary':{'fields':[{'form_source':'workflow_bill','form_id':-14,'field_id':5,'name':'金额','column_name':'amount','physical_table':'main_a'},
                                       {'form_source':'workflow_formbase','form_id':14,'field_id':5,'name':'数量','column_name':'qty','physical_table':'workflow_form'}]},
                 'models':[{'id':8,'name':'模块甲','configuration':{'formid':-14}}]},
          '_source_database':'fixture'}
    t={'Workflow_Report':[{'id':1,'reportname':'标准','formId':-14,'isbill':'1','reportwfid':'1'}],
       'workflow_customreport':[{'id':1,'reportname':'统计','formid':14,'isbill':'0','workflowid':'2'}],
       'mode_report':[{'id':1,'reportname':'模型报表','formId':-14,'modeid':8}],
       'mode_customsearch':[{'id':1,'customname':'列表','formid':-14,'modeid':8,'defaultsql':'id in(select id from aux)'}],
       'Workflow_ReportDspField':[{'id':1,'reportid':1,'fieldid':5,'isstat':'1'}],
       'workflow_customreport_field':[{'reportid':1,'fieldid':5}],
       'mode_ReportDspField':[{'id':1,'reportid':1,'fieldid':5,'isstat':'1'}],
       'mode_CustomDspField':[{'id':1,'customid':1,'fieldid':5}],
       'workflow_customreport_project':[{'id':1,'reportid':1,'projectname':'计算','formula':'EXEC never_run'}],
       'ModeFormExtend':[{'formid':-14,'isvirtualform':'1','vdatasource':'external','vsql':'select * from aux','vprimarykey':'key'}],
       'workflow_customreport_template':[{'id':9,'reportid':1,'templatename':'条件'}],
       'workflow_customreport_tfield':[{'templateid':9,'fieldid':5,'opt1':'>','value1':'10'}],
       'WorkflowReportShare':[{'id':1,'reportid':1,'sharetype':4}],
       'mode_searchPageshareinfo':[{'id':1,'pageid':1,'righttype':1,'sharetype':4}],
       'workflow_report_competence':[{'id':1,'formid':-14,'isbill':'1','type':'x'}],
       'B06_modeinfo':[{'id':8,'formid':-14}],
       'B06_workflow_billfield':[{'id':5,'billid':-14}]}
    return t,seed
def normalize(t,s):
    from categories import b07
    return b07.normalize(t,s)
class B07Tests(unittest.TestCase):
    def test_same_report_id_keeps_four_namespaces_and_signed_form_fields(self):
        t,s=fixture();n=normalize(t,s);self.assertEqual(len(n.get('reports',[])),4)
        d={x['kind']:x for x in n['reports']}
        self.assertEqual(d['workflow_standard']['fields'][0]['field_reference']['name'],'金额')
        self.assertEqual(d['workflow_custom']['fields'][0]['field_reference']['name'],'数量')
    def test_workflow_csv_is_strict_shared_and_conflict_is_preserved(self):
        t,s=fixture();t['Workflow_Report'][0]['reportwfid']='1, 2';n=normalize(t,s)
        r=next(r for r in n['reports'] if r['kind']=='workflow_standard')
        self.assertEqual(r['explicit_workflow_ids'],[1,2])
        self.assertIn('report_workflow_form_conflict',[x['kind'] for x in n['issues']])
        t['Workflow_Report'][0]['reportwfid']='1;2'
        self.assertEqual(next(r for r in normalize(t,s)['reports'] if r['kind']=='workflow_standard')['workflow_list_state'],'unparsed')
    def test_nonzero_invalid_model_form_does_not_silently_fall_back(self):
        t,s=fixture();t['mode_report'][0]['formId']=777
        r=next(r for r in normalize(t,s)['reports'] if r['kind']=='model_report')
        self.assertEqual(r['form_id'],777);self.assertIsNone(r['fields'][0]['field_reference'])
    def test_zero_legacy_list_form_uses_explicit_model_reference(self):
        t,s=fixture();t['mode_customsearch'][0]['formid']=0
        r=next(r for r in normalize(t,s)['reports'] if r['kind']=='model_search')
        self.assertEqual(r['form_id'],-14);self.assertEqual(r['form_basis'],'module_reference_fallback')
    def test_internal_and_missing_fields_are_not_borrowed(self):
        t,s=fixture();t['Workflow_ReportDspField']=[{'id':1,'reportid':1,'fieldid':-1},{'id':2,'reportid':1,'fieldid':999}]
        r=next(r for r in normalize(t,s)['reports'] if r['kind']=='workflow_standard')
        self.assertEqual(r['fields'][0]['field_reference']['namespace'],'report_internal_unverified')
        self.assertIsNone(r['fields'][1]['field_reference'])
    def test_saved_filter_fields_use_their_parent_report_namespace(self):
        t,s=fixture();n=normalize(t,s)
        r=next(r for r in n['reports'] if r['kind']=='workflow_custom')
        self.assertEqual(r['saved_filters'][0]['field_reference']['name'],'数量')
    def test_formula_is_inert_and_external_virtual_sql_is_not_local(self):
        t,s=fixture();n=normalize(t,s)
        r=next(r for r in n['reports'] if r['kind']=='workflow_custom')
        self.assertEqual(r['calculations'][0]['configuration']['formula'],'EXEC never_run')
        self.assertFalse(n['runtime_verified'])
        v=next(x for x in n['sql_source_candidates'] if x['source']=='ModeFormExtend')
        self.assertFalse(v['local_database_candidate'])
    def test_orphan_children_are_preserved_and_coverage_counts_rows(self):
        t,s=fixture();t['workflow_customreport_tfield'].append({'templateid':404,'fieldid':7})
        n=normalize(t,s)
        self.assertEqual(len(n['unassociated_configurations']),1)
        for name,rows in t.items():self.assertEqual(n['source_coverage'][name]['represented_records'],len(rows))
        self.assertEqual(n['source_coverage']['B06_modeinfo']['role'],'dependency_validation')
    def test_two_detail_references_with_aggregation_are_review_candidate(self):
        t,s=fixture()
        s['B06']['dictionary']['fields'] += [{'form_source':'workflow_bill','form_id':-14,'field_id':6,'name':'甲明细','physical_table':'dt_a','configuration':{'viewtype':1}},
                                            {'form_source':'workflow_bill','form_id':-14,'field_id':7,'name':'乙明细','physical_table':'dt_b','configuration':{'viewtype':1}}]
        t['mode_ReportDspField'] += [{'id':2,'reportid':1,'fieldid':6},{'id':3,'reportid':1,'fieldid':7}]
        n=normalize(t,s);self.assertIn('multiple_detail_aggregation_review',[x['kind'] for x in n['issues']])
    def test_untrusted_markup_and_literal_credentials_are_passive_in_reports(self):
        t,s=fixture();t['mode_customsearch'][0]['customname']='<script>bad()</script>';t['mode_customsearch'][0]['defaultsql']="select * from aux where password='fixtureSecret'"
        n=normalize(t,s);self.assertNotIn('fixtureSecret',json.dumps(n))
        from catalog_reports import report
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);report(p,{'started_at':'2026-11-11T01:00:00+00:00','ended_at':'2026-11-11T01:00:01+00:00'},n,{'status':'baseline'})
            self.assertTrue((p/'B07关联报表.html').exists())
            for f in p.glob('*.html'):
                text=f.read_text('utf-8');self.assertNotIn('<script>',text);self.assertNotIn('fixtureSecret',text)

    def test_absent_current_field_keeps_backup_separate(self):
        t,s=fixture();t['Workflow_ReportDspField']=[{'id':1,'reportid':1,'fieldid':None,'fieldidbak':5}]
        n=normalize(t,s);r=next(r for r in n['reports'] if r['kind']=='workflow_standard');f=r['fields'][0]
        self.assertIsNone(f['field_reference']);self.assertEqual(f['backup_field_reference']['name'],'金额')
        self.assertEqual(f['field_state'],'current_binding_absent_backup_retained')
        self.assertNotIn('report_field_reference_unparsed',[x['kind'] for x in n['issues']])
    def test_same_form_module_outside_b06_is_read_and_named(self):
        t,s=fixture();t['mode_report'][0]['modeid']=9;t['modeinfo']=[{'id':9,'formid':-14,'modename':'同表单模块乙'}]
        r=next(r for r in normalize(t,s)['reports'] if r['kind']=='model_report')
        self.assertEqual(r['model_reference']['name'],'同表单模块乙')

    def test_out_of_range_workflow_reference_is_unparsed_without_losing_form_report(self):
        t,s=fixture();t['Workflow_Report'][0]['reportwfid']='1,999999999999'
        r=next(r for r in normalize(t,s)['reports'] if r['kind']=='workflow_standard')
        self.assertEqual(r['workflow_list_state'],'unparsed');self.assertEqual(r['explicit_workflow_ids'],[])

    def test_model_report_links_back_through_b06_reference_reachability(self):
        t,s=fixture();s['B06']['workflow_links']=[{'id':88,'name':'引用模型的另一个流程','reachable_model_ids':[8]}]
        r=next(r for r in normalize(t,s)['reports'] if r['kind']=='model_search')
        self.assertEqual(r.get('model_reference_workflow_candidates'),[88])
        self.assertEqual(r['form_workflow_candidates'],[1])
