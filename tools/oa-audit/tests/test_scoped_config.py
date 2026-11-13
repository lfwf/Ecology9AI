import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scoped_config import scoped_sql
class ScopeTests(unittest.TestCase):
 def test_directory_scope_is_bound(self):
  s=scoped_sql('x','SELECT * FROM dbo.x WHERE workflowid IN (SELECT id FROM dbo.workflow_base)',False)
  self.assertIn('WHERE id=@workflow',s)
 def test_form_scope_is_bound(self):
  s=scoped_sql('x',"SELECT * FROM dbo.x WHERE billid IN (SELECT formid FROM dbo.workflow_base WHERE isbill='1')",False)
  self.assertIn("WHERE id=@workflow AND isbill='1'",s)
 def test_alias_scope_is_bound(self):
  s=scoped_sql('x','SELECT * FROM dbo.x c WHERE EXISTS(SELECT 1 FROM dbo.workflow_base b WHERE b.formid=c.formid)',False)
  self.assertIn('WHERE b.id=@workflow AND',s)
 def test_unscoped_source_fails_closed(self):
  with self.assertRaises(ValueError):scoped_sql('x','SELECT * FROM dbo.x',False)
 def test_reference_scope_only_accepts_registered_placeholder(self):
  self.assertIn('{scope_ids}',scoped_sql('x','SELECT * FROM dbo.x WHERE id IN ({scope_ids})',True))
  with self.assertRaises(ValueError):scoped_sql('x','SELECT * FROM dbo.x',True)
 def test_schedule_is_exact_task_scoped(self):
  s=scoped_sql('schedulesetting',"SELECT * FROM dbo.schedulesetting c WHERE c.classpath LIKE '%workflow%'",False)
  self.assertIn('c.classpath=@jobclass',s)
