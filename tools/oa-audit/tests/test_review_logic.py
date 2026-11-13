import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_logic import formula_assignment,formula_references,rebuild_on_save,candidate_exits
class ReviewLogicTests(unittest.TestCase):
 def test_formula_assignment_requires_lhs_and_single_equal(self):
  self.assertEqual(formula_assignment('[detail_1.42]=IF([main.7]==1,2,3)'),('detail_1',42))
  self.assertIsNone(formula_assignment('[main.7]==1'))
  self.assertEqual(formula_references('[sys.-1]+[main.7]+[detail_2.9]'),[('main',7),('detail_2',9)])
 def test_rebuild_requires_save_event_and_reachable_helper_call(self):
  source='WfForm.registerCheckEvent(WfForm.OPER_SAVE,function(cb){WfForm.delDetailRow("detail_2","all");addrow("detail_2");cb();});function addrow(d){WfForm.addDetailRow(d,{});}'
  self.assertTrue(rebuild_on_save(source))
  self.assertFalse(rebuild_on_save(source.replace('addrow("detail_2");','')))
  self.assertFalse(rebuild_on_save('/*'+source+'*/'))
 def test_default_and_specific_route_overlap_is_exposed(self):
  r=[dict(id=1,rules=[],condition_state='no_condition_definition_observed'),dict(id=2,rules=[dict(terms=[dict(field_reference={'field_id':7},configuration={'compareoption1':7,'elementvalue1':'3'})])])]
  self.assertEqual(candidate_exits(r,'3',7),{'candidate_routes':[1,2],'unresolved_routes':[]})
  self.assertEqual(candidate_exits(r,'2',7)['candidate_routes'],[1])
  self.assertEqual(candidate_exits(r,None,7)['unresolved_routes'],[2])
