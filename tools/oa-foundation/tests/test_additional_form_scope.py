import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_b02 import fixture
class AdditionalFormScopeTests(unittest.TestCase):
    def test_additional_model_form_has_no_invented_workflow(self):
        from categories.b02 import normalize
        tables,seed=fixture()
        extra=dict(tables['workflow_bill'][0],id=-999,tablename='uf_extra')
        tables['workflow_bill'].append(extra)
        seed['additional_form_scopes']=[dict(form_source='workflow_bill',form_id=-999)]
        doc=normalize(tables,seed)
        form=next((f for f in doc['forms'] if f['form_id']==-999),None)
        self.assertIsNotNone(form);self.assertEqual(form['workflow_ids'],[])
if __name__=='__main__':unittest.main()
