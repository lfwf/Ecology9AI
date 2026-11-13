import copy,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import foundation as f,catalog_store as store
from test_b09 import fixture
from runtime_references import digest

def capture():
    t,s=fixture();m=store.method('B09')
    for row in t['local_reference_files']:row['runtime_verified']=False
    rows=t['local_reference_files']
    proof=dict(category='B09_reference_sources',method_version='1.0.0',status='captured',two_reads_equal=True,profile_and_code_stable=True,
        profile_sha256='synthetic',implementation_hashes={'synthetic':'hash'},expected_reference_keys=[r['reference_key'] for r in rows],
        files_sha256=digest(rows),second_files_sha256=digest(rows))
    raw=dict(format_version=1,category='B09',method_version=m['method_version'],scope=m['scope'],started_at='2026-11-11T01:00:00+00:00',
        ended_at='2026-11-11T01:00:01+00:00',source_identity={'database':'synthetic'},business_rows_read=0,schema={'objects':[{'column_name':'object_name','data_type':'System.String'}]},
        tables=t,reference_evidence=proof,checks={n:dict(complete=True,row_count=len(v),hash_first=digest(v),hash_second=digest(v),pages=[]) for n,v in t.items()})
    return raw,s

class B09StoreTests(unittest.TestCase):
    def test_missing_or_changed_reference_proof_cannot_publish(self):
        for change in ['missing','hash']:
            raw,s=capture()
            if change=='missing':del raw['reference_evidence']
            else:raw['tables']['local_reference_files'][0]['snippets'].append({'line':3,'text':'changed'})
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(ValueError):store.validate(raw,store.method('B09'))
                self.assertIsNone(store.status(Path(td),'fixture','B09')['latest_success'])
    def test_column_addition_is_data_diff_with_same_result_contract(self):
        raw,s=capture()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=store.publish(root,'fixture',raw,s,{'B01':'synthetic','B08':'synthetic'})
            old=(a/'raw.json').read_bytes()
            raw['tables']['columns'].append(dict(raw['tables']['columns'][0],column_id=200,column_name='new_metadata_column'))
            rows=raw['tables']['columns'];raw['checks']['columns'].update(row_count=len(rows),hash_first=digest(rows),hash_second=digest(rows))
            b=store.publish(root,'fixture',raw,s,{'B01':'synthetic','B08':'synthetic'})
            diff=f.read_json(b/'diff.json')
            self.assertEqual(diff['status'],'compared');self.assertEqual(len(diff['sources']['columns']['added']),1)
            self.assertEqual(old,(a/'raw.json').read_bytes())
            self.assertIsNone(store.status(root,'fixture','B09')['latest_reviewed'])
            with self.assertRaises(ValueError):store.selected_batch(root,'fixture','B09')
    def test_registered_small_metadata_cap_is_enforced(self):
        raw,s=capture()
        raw['tables']['view_definitions']*=21
        raw['checks']['view_definitions'].update(row_count=21)
        with self.assertRaises(ValueError):store.validate(raw,store.method('B09'))
