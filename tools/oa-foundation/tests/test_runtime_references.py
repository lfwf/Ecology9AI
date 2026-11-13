import json,sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
class RuntimeReferenceTests(unittest.TestCase):
    def test_reference_lines_are_sanitized_and_not_treated_as_enumeration(self):
        from runtime_references import collect_reference_files
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'A.java';p.write_text('class A {\nString token="fixtureSecret"; // status\n}\n','utf-8')
            pr={'roots':[str(root)],'references':[{'key':'a','path':str(p),'markers':['status'],'topics':[{'object_name':'obj','columns':['status'],'note':'local only'}]}]}
            rows=collect_reference_files(pr);self.assertTrue(rows[0]['available'])
            self.assertNotIn('fixtureSecret',json.dumps(rows));self.assertEqual(rows[0]['snippets'][1]['line'],2)
            self.assertEqual(rows[0]['evidence_state'],'local_reference_only_not_loaded')
    def test_log_files_and_outside_roots_are_rejected(self):
        from runtime_references import collect_reference_files
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'data.log';p.write_text('must not be read','utf-8')
            pr={'roots':[str(root)],'references':[{'key':'bad','path':str(p),'markers':[],'topics':[]}]}
            with self.assertRaises(ValueError):collect_reference_files(pr)
            other=root/'allowed';other.mkdir();pr['roots']=[str(other)];pr['references'][0]['path']=str(root/'A.java')
            with self.assertRaises(ValueError):collect_reference_files(pr)
    def test_missing_source_is_explicit_and_capture_is_immutable(self):
        from runtime_references import capture_references
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'profile.json';out=root/'out'/'capture.json'
            p.write_text(json.dumps({'roots':[str(root/'sources')],'references':[{'key':'missing','path':str(root/'sources'/'A.java'),'markers':['status'],'topics':[]}]}),'utf-8')
            d=capture_references(p,out);self.assertTrue(d['two_reads_equal']);self.assertFalse(d['files'][0]['available'])
            original=out.read_bytes()
            with self.assertRaises(FileExistsError):capture_references(p,out)
            self.assertEqual(out.read_bytes(),original)
