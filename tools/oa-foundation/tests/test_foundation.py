"""Synthetic fixtures only; no database or enterprise snapshots needed."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fixture():
    tables = {
        'workflow_base': [dict(id=10, workflowname='采购样例', workflowtype=2,
                              formid=-7, isbill='1', isvalid='?', version=None,
                              activeVersionID=10, istemplate='0', templateid=None,
                              isfree='0', subcompanyid=1)],
        'workflow_type': [dict(id=2, typename='采购类')],
        'workflow_bill': [dict(id=-7, tablename='formtable_main_7', namelabel=1, invalid=0)],
        'workflow_formbase': [dict(id=-7, formname='旧式同号样例')],
    }
    return dict(format_version=1, method_version='1.0.0', category='B01',
                started_at='2026-11-11T01:00:00+00:00', ended_at='2026-11-11T01:00:01+00:00',
                source_identity=dict(server='synthetic', database='fixture', login='reader'),
                transport=dict(encrypt=True, trust_server_certificate=True),
                schema=[dict(object_name=t, column_name='id', data_type='int') for t in tables],
                tables=tables, checks={t: dict(complete=True, row_count=len(rows),
                     hash_first='same', hash_second='same') for t, rows in tables.items()})


class FoundationTests(unittest.TestCase):
    def setUp(self):
        import foundation
        self.api = foundation
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_signed_form_id_and_namespace_are_preserved(self):
        doc = self.api.normalize(fixture())
        row = doc['workflows'][0]
        self.assertEqual(row['form_id'], -7)
        self.assertEqual(row['form_source'], 'workflow_bill')
        self.assertEqual(row['form_table'], 'formtable_main_7')
        self.assertEqual(row['isvalid_raw'], '?')
        self.assertNotIn('enabled', row)

    def test_old_form_is_separate_namespace(self):
        raw = fixture()
        raw['tables']['workflow_base'][0]['isbill'] = '0'
        row = self.api.normalize(raw)['workflows'][0]
        self.assertEqual(row['form_source'], 'workflow_formbase')
        self.assertEqual(row['form_name'], '旧式同号样例')
        self.assertIsNone(row['form_table'])

    def test_unknown_selector_does_not_guess(self):
        raw = fixture()
        raw['tables']['workflow_base'][0]['isbill'] = 'x'
        doc = self.api.normalize(raw)
        self.assertIsNone(doc['workflows'][0]['form_source'])
        self.assertIn('unknown_form_selector', {i['kind'] for i in doc['issues']})

    def test_shared_form_and_duplicate_names_keep_both_workflows(self):
        raw = fixture()
        raw['tables']['workflow_base'].append(dict(raw['tables']['workflow_base'][0], id=11))
        raw['checks']['workflow_base']['row_count'] = 2
        doc = self.api.normalize(raw)
        self.assertEqual(len(doc['workflows']), 2)
        self.assertEqual(doc['shared_forms'][0]['workflow_ids'], [10, 11])
        self.assertIn('duplicate_name', {i['kind'] for i in doc['issues']})

    def test_missing_references_and_blank_name_are_issues(self):
        raw = fixture()
        raw['tables']['workflow_base'][0].update(workflowname='', workflowtype=9,
                                                formid=7, activeVersionID=999)
        kinds = {i['kind'] for i in self.api.normalize(raw)['issues']}
        self.assertTrue({'missing_category', 'missing_form', 'missing_active_version', 'blank_name'} <= kinds)

    def test_incomplete_changed_empty_or_duplicate_reads_rejected(self):
        cases = []
        raw = fixture(); raw['checks']['workflow_base']['complete'] = False; cases.append(raw)
        raw = fixture(); raw['checks']['workflow_base']['hash_second'] = 'changed'; cases.append(raw)
        raw = fixture(); raw['checks']['workflow_base']['row_count'] = 2; cases.append(raw)
        raw = fixture(); raw['tables']['workflow_base'] = []; raw['checks']['workflow_base']['row_count'] = 0; cases.append(raw)
        raw = fixture(); raw['tables']['workflow_base'].append(raw['tables']['workflow_base'][0]); raw['checks']['workflow_base']['row_count'] = 2; cases.append(raw)
        raw = fixture(); del raw['tables']['workflow_base'][0]['formid']; cases.append(raw)
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.api.normalize(raw)

    def test_first_batch_is_baseline_and_files_not_overwritten(self):
        a = self.api.publish(self.root, 'fixture', fixture())
        before = (a / 'raw.json').read_bytes()
        b = self.api.publish(self.root, 'fixture', fixture())
        self.assertNotEqual(a, b)
        self.assertEqual((a / 'raw.json').read_bytes(), before)
        self.assertEqual(json.loads((a / 'diff.json').read_text('utf-8'))['status'], 'baseline')
        self.assertEqual(json.loads((b / 'diff.json').read_text('utf-8'))['status'], 'compared')
        self.assertEqual(json.loads((b / 'diff.json').read_text('utf-8'))['changed'], [])

    def test_diff_records_added_changed_and_source_missing(self):
        self.api.publish(self.root, 'fixture', fixture())
        raw = fixture()
        raw['tables']['workflow_base'][0]['workflowname'] = '改名'
        a = self.api.publish(self.root, 'fixture', raw)
        diff = json.loads((a / 'diff.json').read_text('utf-8'))
        self.assertEqual(diff['changed'][0]['id'], 10)
        self.assertIn('workflowname', diff['changed'][0]['fields'])
        raw['tables']['workflow_base'][0]['id'] = 11
        b = self.api.publish(self.root, 'fixture', raw)
        diff = json.loads((b / 'diff.json').read_text('utf-8'))
        self.assertEqual(diff['added'], [11])
        self.assertEqual(diff['source_missing'], [10])

    def test_dictionary_change_is_in_diff(self):
        self.api.publish(self.root, 'fixture', fixture())
        raw = fixture(); raw['tables']['workflow_type'][0]['typename'] = '新类别'
        batch = self.api.publish(self.root, 'fixture', raw)
        diff = json.loads((batch / 'diff.json').read_text('utf-8'))
        self.assertEqual(diff['sources']['workflow_type']['changed'][0]['id'], 2)

    def test_method_schema_and_source_changes_are_not_business_diffs(self):
        for mode in ['method', 'schema', 'source']:
            root = self.root / mode
            self.api.publish(root, 'fixture', fixture())
            raw = fixture()
            if mode == 'method': raw['method_version'] = '2.0.0'
            if mode == 'schema': raw['schema'][0]['data_type'] = 'bigint'
            if mode == 'source': raw['source_identity']['database'] = 'different'
            batch = self.api.publish(root, 'fixture', raw)
            diff = json.loads((batch / 'diff.json').read_text('utf-8'))
            self.assertEqual(diff['status'], 'not_comparable')
            self.assertNotIn('added', diff)

    def test_failed_publish_preserves_success_pointer(self):
        self.api.publish(self.root, 'fixture', fixture())
        before = self.api.status(self.root, 'fixture')
        raw = fixture(); raw['checks']['workflow_bill']['complete'] = False
        with self.assertRaises(ValueError): self.api.publish(self.root, 'fixture', raw)
        self.assertEqual(self.api.status(self.root, 'fixture'), before)

    def test_late_older_capture_cannot_replace_newer_success(self):
        newer = fixture()
        newer.update(started_at='2026-11-11T01:01:00+00:00', ended_at='2026-11-11T01:01:01+00:00')
        batch = self.api.publish(self.root, 'fixture', newer)
        with self.assertRaises(ValueError): self.api.publish(self.root, 'fixture', fixture())
        self.assertEqual(self.api.status(self.root, 'fixture')['latest_success'], batch.name)

    def test_review_is_separate_and_default_requires_acceptance(self):
        a = self.api.publish(self.root, 'fixture', fixture())
        with self.assertRaises(ValueError): self.api.selected_batch(self.root, 'fixture')
        self.api.review(self.root, 'fixture', a.name, 'tester', 'accepted', '核对范围', 'partial')
        b = self.api.publish(self.root, 'fixture', fixture())
        self.assertEqual(self.api.selected_batch(self.root, 'fixture').name, a.name)
        self.assertEqual(self.api.selected_batch(self.root, 'fixture', unreviewed=True).name, b.name)
        self.assertEqual(len(list((self.root / 'fixture' / 'B01' / 'reviews').glob('*.json'))), 1)

    def test_new_environment_is_independent_baseline(self):
        self.api.publish(self.root, 'one', fixture())
        a = self.api.publish(self.root, 'two', fixture())
        self.assertEqual(json.loads((a / 'diff.json').read_text('utf-8'))['status'], 'baseline')

    def test_reviewed_batch_from_different_source_is_not_default_knowledge(self):
        a = self.api.publish(self.root, 'fixture', fixture())
        self.api.review(self.root, 'fixture', a.name, 'tester', 'accepted', '同意范围', 'partial')
        raw = fixture(); raw['source_identity']['database'] = 'other_database'
        self.api.publish(self.root, 'fixture', raw)
        with self.assertRaises(ValueError):
            self.api.selected_batch(self.root, 'fixture')

    def test_tampered_batch_cannot_be_reviewed(self):
        a = self.api.publish(self.root, 'fixture', fixture())
        (a / 'raw.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.api.review(self.root, 'fixture', a.name, 'tester', 'accepted', '同意', 'partial')

    def test_report_escapes_source_markup_and_csv_formulas(self):
        raw = fixture(); raw['tables']['workflow_base'][0]['workflowname'] = '=1+1<script>boom</script>'
        a = self.api.publish(self.root, 'fixture', raw)
        report = (a / '流程目录.html').read_text('utf-8')
        self.assertNotIn('<script>boom', report)
        self.assertIn('&lt;script&gt;', report)
        self.assertIn("'=1+1", (a / '流程目录.csv').read_text('utf-8-sig'))

    def test_environment_path_traversal_rejected(self):
        with self.assertRaises(ValueError): self.api.publish(self.root, '../outside', fixture())

    def test_cli_failure_writes_attempt_without_success(self):
        script = Path(__file__).resolve().parents[1] / 'run.py'
        result = subprocess.run([sys.executable, str(script), '--data-root', str(self.root),
                                 '--environment', 'fixture', 'refresh', '--connection-directory',
                                 str(self.root / 'absent')], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(self.api.status(self.root, 'fixture')['latest_success'])
        attempts = list((self.root / 'fixture' / 'B01' / 'attempts').glob('*/result.json'))
        self.assertEqual(len(attempts), 1)
        self.assertEqual(json.loads(attempts[0].read_text('utf-8'))['status'], 'failed')

    def test_cli_show_defaults_to_reviewed_batch(self):
        self.api.publish(self.root, 'fixture', fixture())
        script = Path(__file__).resolve().parents[1] / 'run.py'
        command = [sys.executable, str(script), '--data-root', str(self.root), '--environment', 'fixture', 'show']
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        result = subprocess.run(command + ['--unreviewed'], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_accepted_knowledge_discloses_new_unreviewed_capture(self):
        a = self.api.publish(self.root, 'fixture', fixture())
        self.api.review(self.root, 'fixture', a.name, 'tester', 'accepted', '已审范围', 'partial')
        b = self.api.publish(self.root, 'fixture', fixture())
        script = Path(__file__).resolve().parents[1] / 'run.py'
        result = subprocess.run([sys.executable, str(script), '--data-root', str(self.root),
                                 '--environment', 'fixture', 'show'], capture_output=True)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertTrue(data.get('has_unreviewed_update'))
        self.assertEqual(data['latest_success'], b.name)


if __name__ == '__main__':
    unittest.main()
