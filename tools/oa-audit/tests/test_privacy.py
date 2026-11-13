import sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from privacy import validate_packet,business_counts
class PrivacyTests(unittest.TestCase):
 def packet(self):return {'scope':'sales_sample_review','counts':{'requests':10},'finding_counts':{},'node_checks':[]}
 def test_unknown_fields_rejected(self):
  p=self.packet();p['customer_name']='PRIVATE_CUSTOMER'
  with self.assertRaises(ValueError):validate_packet(p)
 def test_string_cannot_be_smuggled_as_count(self):
  p=self.packet();p['counts']['requests']='PRIVATE_SUPPLIER 199.95'
  with self.assertRaises(ValueError):validate_packet(p)
 def test_nested_text_rejected(self):
  p=self.packet();p['node_checks']=[dict(node_id=1,permissions=2,required_locked=0,missing_permissions=0,operator_rules=1,sql='PRIVATE')]
  with self.assertRaises(ValueError):validate_packet(p)
 def test_boolean_and_negative_counts_rejected(self):
  for v in [True,-1,1.23]:
   p=self.packet();p['counts']['requests']=v
   with self.assertRaises(ValueError):validate_packet(p)
 def test_business_projection_keeps_counts_only(self):
  src={'summary':{'requests':2,'archived':1,'original_quantity':'999.95','customer_name':'PRIVATE_CUSTOMER','supplier_name':'PRIVATE_SUPPLIER'},'rows':[{'amount':'999.95','customer_name':'PRIVATE_CUSTOMER'}]}
  out=business_counts(src);serialized=json.dumps(out)
  for value in ['999.95','PRIVATE_CUSTOMER','PRIVATE_SUPPLIER','rows']:self.assertNotIn(value,serialized)
  self.assertEqual(out,{'requests':2,'archived':1})
 def test_approved_packet_passes(self):self.assertEqual(validate_packet(self.packet()),self.packet())

 def test_cost_center_scope_uses_same_strict_boundary(self):
  p=self.packet();p['scope']='cost_center_review'
  self.assertEqual(validate_packet(p)['scope'],'cost_center_review')
