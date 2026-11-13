import sys,tempfile,json,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import foundation as f
from test_foundation import fixture

class OverviewTests(unittest.TestCase):
    def test_missing_categories_are_explicit_not_a_completed_system(self):
        from overview import inspect_environment,write_overview
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);r=inspect_environment(root,'fixture')
            self.assertFalse(r['all_categories_present']);self.assertEqual(len(r['categories']),9)
            self.assertEqual({x['state'] for x in r['categories']},{'not_captured'})
            out=write_overview(root,'fixture')
            self.assertTrue(out.is_file());self.assertNotIn('<script',out.read_text('utf-8'))
    def test_pending_capture_links_resolve_and_no_review_is_created(self):
        from overview import inspect_environment,write_overview
        from html.parser import HTMLParser
        from urllib.parse import unquote
        class Links(HTMLParser):
            def __init__(self):super().__init__();self.links=[]
            def handle_starttag(self,tag,attrs):
                if tag=='a':self.links.extend(v for k,v in attrs if k=='href')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);batch=f.publish(root,'fixture',fixture())
            r=inspect_environment(root,'fixture');first=r['categories'][0]
            self.assertEqual(first['state'],'pending');self.assertEqual(first['batch_id'],batch.name)
            out=write_overview(root,'fixture');p=Links();p.feed(out.read_text('utf-8'))
            self.assertTrue(p.links)
            for link in p.links:self.assertTrue((out.parent/unquote(link)).is_file(),link)
            self.assertIsNone(f.status(root,'fixture')['latest_reviewed'])
    def test_tampered_batch_fails_integrity_check(self):
        from overview import inspect_environment
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);batch=f.publish(root,'fixture',fixture())
            with (batch/'normalized.json').open('a',encoding='utf-8') as stream:stream.write(' ')
            with self.assertRaises(ValueError):inspect_environment(root,'fixture')
    def test_unsafe_environment_is_rejected(self):
        from overview import inspect_environment
        with self.assertRaises(ValueError):inspect_environment(Path('unused'),'../outside')

    def test_legacy_category_reports_missing_uniform_coverage_counter_honestly(self):
        from overview import inspect_environment
        from test_catalog_store import capture
        import catalog_store
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);f.publish(root,'fixture',fixture())
            raw,seed=capture();catalog_store.publish(root,'fixture',raw,seed,{'B01':{'batch_id':f.status(root,'fixture')['latest_success'],'raw_sha256':__import__('hashlib').sha256((f.selected_batch(root,'fixture',True)/'raw.json').read_bytes()).hexdigest()}})
            entry=inspect_environment(root,'fixture')['categories'][1]
            self.assertEqual(entry['normalized_coverage_state'],'not_recorded_in_legacy_format')
    def test_partitioned_coverage_requires_full_balance(self):
        from overview import coverage_state
        self.assertEqual(coverage_state('B05',{'source_coverage':{'x':{'raw_records':2,'associated_records':1,'unassociated_records':1}}},{'x':[{},{}]}),'partition_counts_verified')
        with self.assertRaises(ValueError):coverage_state('B05',{'source_coverage':{'x':{'raw_records':2,'associated_records':1,'unassociated_records':0}}},{'x':[{},{}]})

    def test_manifest_cannot_omit_modified_normalized_file(self):
        from overview import inspect_environment
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);batch=f.publish(root,'fixture',fixture())
            manifest=f.read_json(batch/'manifest.json');del manifest['files']['normalized.json']
            (batch/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            doc=f.read_json(batch/'normalized.json');doc['semantic_state']='forged'
            (batch/'normalized.json').write_text(json.dumps(doc),encoding='utf-8')
            with self.assertRaises(ValueError):inspect_environment(root,'fixture')
    def test_unmanifested_extra_file_is_not_claimed_hash_verified(self):
        from overview import inspect_environment
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);batch=f.publish(root,'fixture',fixture())
            (batch/'extra.html').write_text('not hashed',encoding='utf-8')
            with self.assertRaises(ValueError):inspect_environment(root,'fixture')

    def test_dependency_batch_requires_complete_manifest_too(self):
        from overview import inspect_environment
        from test_catalog_store import capture
        import catalog_store,hashlib
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=f.publish(root,'fixture',fixture());f.publish(root,'fixture',fixture())
            raw,seed=capture()
            deps={'B01':dict(batch_id=a.name,raw_sha256=hashlib.sha256((a/'raw.json').read_bytes()).hexdigest())}
            catalog_store.publish(root,'fixture',raw,seed,deps)
            manifest=f.read_json(a/'manifest.json');del manifest['files']['normalized.json']
            (a/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaises(ValueError):inspect_environment(root,'fixture')
