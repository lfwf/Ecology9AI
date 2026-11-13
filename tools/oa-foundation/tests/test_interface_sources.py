import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_b08 import fixture
def raw_capture():
    from interface_sources import registration_rows,digest
    from source_evidence import VERSION
    import catalog_store
    t,s=fixture();m=catalog_store.method('B08')
    t={name:t.get(name,[]) for name in list(m['sources'])+m['metadata_sources']}
    for file in t['local_source_files']:file['evidence']['executed']=False
    rows=registration_rows(t);graph=dict(registrations=[dict(registration_id=x['id'],class_name=x['actionclass'],file_keys=['source1'],lookup_state='files_visible') for x in rows],edges=[],frontier=[],closed=True)
    total=dict(graph,files=t['local_source_files'])
    header=dict(format_version=1,category='B08_source_evidence',method_version=VERSION,status='captured',two_reads_equal=True,input_and_profile_stable=True,implementation_stable=True,
                profile_sha256='a'*64,implementation_hashes={'reader':'b'*64},graph=graph,registration_rows_sha256=digest(rows),evidence_sha256=digest(total),second_evidence_sha256=digest(total))
    raw=dict(format_version=1,category='B08',method_version=m['method_version'],scope=m['scope'],business_rows_read=0,
             started_at='2026-11-11T01:00:00+00:00',ended_at='2026-11-11T01:00:01+00:00',source_identity={'server':'fixture','database':'fixture'},
             schema=[{'object_name':'workflowactionset'}],tables=t,source_evidence=header,reference_graph=dict(closed=True,iterations=[{'iteration':0}]),
             checks={n:dict(complete=True,row_count=len(v),hash_first=digest(v),hash_second=digest(v),pages=[] if n in m['metadata_sources'] else [dict(row_count=len(v))]) for n,v in t.items()})
    return raw,s,m
class InterfaceSourceTests(unittest.TestCase):
    def test_current_roots_and_file_rows_are_bound_to_capture_hashes(self):
        from interface_sources import verify_source_capture
        r,s,m=raw_capture();self.assertTrue(verify_source_capture(r)['closed'])
        changed=copy.deepcopy(r);changed['tables']['actionsetting'][0]['actionclass']='demo.Other'
        with self.assertRaises(ValueError):verify_source_capture(changed)
        changed=copy.deepcopy(r);changed['tables']['local_source_files'][0]['sha256']='changed'
        with self.assertRaises(ValueError):verify_source_capture(changed)
    def test_store_rejects_open_or_mismatched_code_scope_before_publish(self):
        import catalog_store
        r,s,m=raw_capture();catalog_store.validate(r,m)
        r['source_evidence']['graph']['closed']=False
        with self.assertRaises(ValueError):catalog_store.validate(r,m)
    def test_source_graph_may_not_claim_code_execution(self):
        from interface_sources import verify_source_capture,digest
        r,s,m=raw_capture();r['tables']['local_source_files'][0]['evidence']['executed']=True
        with self.assertRaises(ValueError):verify_source_capture(r)
