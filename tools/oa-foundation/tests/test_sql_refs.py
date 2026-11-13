import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
class SqlReferenceTests(unittest.TestCase):
    def refs(self,text):
        from sql_refs import table_references
        return table_references(text)
    def test_comments_strings_and_nested_comments_are_inert(self):
        d=self.refs("SELECT 'from uf_fake' FROM dbo.uf_real /* outer /* JOIN uf_fake2 */ JOIN uf_fake3 */ -- JOIN uf_fake4\n JOIN [uf_second] s ON s.id=1")
        self.assertEqual([r['object_name'] for r in d['candidates']],['uf_real','uf_second'])
    def test_quoted_qualified_identifiers_preserve_parts(self):
        d=self.refs('select * from [otherdb].[custom].[uf_A] a join "dbo"."uf_B" b on 1=1')
        self.assertEqual((d['candidates'][0]['database'],d['candidates'][0]['schema'],d['candidates'][0]['object_name']),('otherdb','custom','uf_A'))
        self.assertEqual(d['candidates'][1]['schema'],'dbo')
    def test_cte_name_is_not_a_physical_table(self):
        d=self.refs('WITH c AS (SELECT * FROM dbo.uf_seed), d AS (SELECT * FROM c) SELECT * FROM d JOIN uf_target ON 1=1')
        self.assertEqual([r['object_name'] for r in d['candidates']],['uf_seed','uf_target'])
    def test_dynamic_and_external_calls_are_not_followed(self):
        d=self.refs("EXEC('SELECT * FROM uf_secret'); SELECT * FROM OPENQUERY(remote,'select * from uf_remote') JOIN @table t ON 1=1")
        self.assertEqual(d['candidates'],[]);self.assertTrue(d['warnings'])
    def test_escaped_identifier_is_data_not_sql(self):
        d=self.refs('select * from [dbo].[uf_a]]b]')
        self.assertEqual(d['candidates'][0]['object_name'],'uf_a]b')
    def test_table_functions_stay_unresolved(self):
        d=self.refs('select * from dbo.tablefunc(@arg)')
        self.assertEqual(d['candidates'],[]);self.assertTrue(d['warnings'])
    def test_cross_database_with_omitted_schema_is_not_a_local_single_name(self):
        for text in ['select * from otherdb..uf_master','select * from [otherdb]..[uf_master]']:
            refs=self.refs(text)['candidates']
            self.assertEqual(len(refs),1)
            self.assertEqual((refs[0]['database'],refs[0]['schema'],refs[0]['object_name']),('otherdb',None,'uf_master'))

    def test_configured_literal_object_name_can_start_with_digit(self):
        from sql_refs import split_identifier
        name='0123456789abcdef0123456789abcdef_cube_vsql'
        ref=split_identifier(name)
        self.assertIsNotNone(ref);self.assertEqual(ref['object_name'],name)
        self.assertEqual(self.refs('select * from ['+name+']')['candidates'][0]['object_name'],name)

if __name__=='__main__':unittest.main()
