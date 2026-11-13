import json,struct,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def profile(root):
    return {'roots':[{'path':str(root),'kind':'both'}],'limits':dict(max_files=40,max_depth=4,max_file_bytes=100000,max_total_bytes=1000000)}
def java(root,name,body):
    p=root/Path(*name.split('.'));p=p.with_suffix('.java');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body,'utf-8');return p
class SourceEvidenceTests(unittest.TestCase):
    def test_registered_class_delegates_to_visible_service_and_base_without_execution(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            java(root,'demo.A','package demo; import demo.service.S; public class A extends Base { public String execute(){ S s=new S(); return s.run(); }}')
            java(root,'demo.Base','package demo; class Base {}')
            java(root,'demo.service.S','package demo.service; class S {String run(){return "ok";}}')
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],profile(root))
            self.assertTrue(d['closed']);self.assertEqual({x['class_name'] for x in d['files']},{'demo.A','demo.Base','demo.service.S'})
            self.assertTrue(all(not x['runtime_loaded_verified'] for x in d['files']))
    def test_same_class_shared_by_registrations_keeps_both_origins_without_duplicate_files(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);java(root,'demo.A','package demo; class A {}')
            d=scan_sources([{'id':1,'actionclass':'demo.A'},{'id':2,'actionclass':'demo.A'}],profile(root))
            self.assertEqual(len(d['registrations']),2);self.assertEqual(len(d['files']),1)
            self.assertEqual(d['registrations'][0]['file_keys'],d['registrations'][1]['file_keys'])
    def test_comments_strings_and_fake_calls_are_not_active_syntax(self):
        from source_evidence import java_evidence
        d=java_evidence('''package demo;
// return Action.SUCCESS; map.get("fake"); new Evil();
/* rs.executeUpdate("delete from business"); */
class A { String note="return Action.FAILURE; new Evil()"; String run(){ return doResult(r.getStatus()); }}''')
        self.assertEqual(len(d['returns']),1)
        self.assertIn('doResult',d['returns'][0]['expression'])
        self.assertEqual(d['field_accesses'],[]);self.assertEqual(d['sql_fragments'],[])
        self.assertNotIn('Evil',d['type_candidates'])
    def test_actual_map_fields_sql_fragments_and_outcome_branches_keep_lines(self):
        from source_evidence import java_evidence
        d=java_evidence('''package demo;
class A {String run(){
String k=main.get("outside_code");
if (result.isSuccess()) { rs.executeUpdate("update dbo.target set code=? where id=?"); return Action.SUCCESS; }
return Action.FAILURE_AND_CONTINUE;
}}''')
        self.assertEqual(d['field_accesses'][0]['field_literal'],'outside_code')
        self.assertEqual(d['returns'][0]['line'],4)
        self.assertEqual(d['sql_fragments'][0]['write_target_candidates'][0]['object_name'],'target')
        self.assertFalse(d['complete_control_flow'])
    def test_dynamic_sql_target_is_not_filled_in_from_variable_name(self):
        from source_evidence import java_evidence
        d=java_evidence('class A {void x(){ rs.executeUpdate("update "+table+" set code=?"); }}')
        self.assertEqual(d['sql_fragments'][0]['write_target_candidates'],[])
        self.assertEqual(d['sql_fragments'][0]['target_state'],'dynamic_or_unresolved')
    def test_literal_secrets_in_java_xml_json_urls_and_headers_are_masked(self):
        from source_evidence import sanitize_text
        raw='''String SAP_PASSWORD="javaSecret";
set("apiToken","setterSecret");
<root><password>xmlSecret
continued</password><x token="attrSecret"/></root>
{"client_secret":"jsonSecret"}
https://example.invalid/path?access_token=urlSecret
Authorization: Bearer bearerSecret
jdbc:sqlserver://host;password=jdbcSecret;databaseName=sample
'''
        value=sanitize_text(raw)
        for secret in ['javaSecret','setterSecret','xmlSecret','continued','attrSecret','jsonSecret','urlSecret','bearerSecret','jdbcSecret']:self.assertNotIn(secret,value)
        self.assertEqual(value.count('\n'),raw.count('\n'))
    def test_cycle_closes_and_unused_import_is_not_followed(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            java(root,'demo.A','package demo; import demo.Unused; class A { B b; }')
            java(root,'demo.B','package demo; class B { A a; }')
            java(root,'demo.Unused','package demo; class Unused {}')
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],profile(root))
            self.assertTrue(d['closed']);self.assertEqual({x['class_name'] for x in d['files']},{'demo.A','demo.B'})
    def test_missing_source_and_invalid_class_names_are_explicit(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            d=scan_sources([{'id':1,'actionclass':'demo.Missing'},{'id':2,'actionclass':'../escape'}],profile(Path(td)))
            self.assertEqual([x['lookup_state'] for x in d['registrations']],['not_visible','invalid_literal_class'])
            self.assertEqual(d['files'],[])
    def test_depth_or_file_limit_has_frontier_and_is_not_declared_closed(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);java(root,'demo.A','package demo; class A {B b;}');java(root,'demo.B','package demo; class B {}')
            pr=profile(root);pr['limits']['max_depth']=0
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],pr)
            self.assertFalse(d['closed']);self.assertEqual(d['frontier'][0]['class_name'],'demo.B')
    def test_source_size_limit_never_returns_false_complete(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);java(root,'demo.A','package demo; class A {}'+' '*1000)
            pr=profile(root);pr['limits']['max_file_bytes']=100
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],pr)
            self.assertFalse(d['closed']);self.assertEqual(d['frontier'][0]['reason'],'file_byte_cap')
    def test_two_independent_reads_have_deterministic_evidence(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=java(root,'demo.A','package demo; class A {}')
            args=([{'id':1,'actionclass':'demo.A'}],profile(root))
            a=scan_sources(*args);b=scan_sources(*args);self.assertEqual(a,b)
            p.write_text('package demo; class A {int changed;}','utf-8')
            self.assertNotEqual(a,scan_sources(*args))
    def test_utf8_and_gbk_sources_keep_chinese_and_reference_line_numbers(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=java(root,'demo.A','package demo;\nclass A {void x(){map.get("项目编号");}}')
            p.write_bytes(p.read_text('utf-8').encode('gb18030'))
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],profile(root))
            self.assertEqual(d['files'][0]['evidence']['field_accesses'][0]['field_literal'],'项目编号')
            self.assertEqual(d['files'][0]['evidence']['field_accesses'][0]['line'],2)
    def test_path_escape_via_symlink_is_not_read(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);root=base/'src';root.mkdir();other=base/'outside';other.mkdir();java(other,'demo.A','class A {}')
            try:(root/'demo').symlink_to(other/'demo',target_is_directory=True)
            except OSError:self.skipTest('Symlink privilege unavailable')
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],profile(root))
            self.assertEqual(d['files'],[]);self.assertEqual(d['registrations'][0]['lookup_state'],'path_outside_root')
    def test_compiled_constant_pool_is_data_and_never_claims_branch_execution(self):
        from source_evidence import class_evidence
        vals=[b'demo/A',b'java/lang/Object',b'run',b'()V',b'update dbo.target set code=?',b'Action.SUCCESS']
        data=b'\xca\xfe\xba\xbe'+struct.pack('>HHH',0,52,len(vals)+1)+b''.join(b'\x01'+struct.pack('>H',len(x))+x for x in vals)
        d=class_evidence(data)
        self.assertEqual(d['evidence_state'],'constant_pool_only')
        self.assertFalse(d['complete_control_flow']);self.assertFalse(d['executed'])
        self.assertTrue(d['sql_fragments'])
    def test_both_source_and_class_copies_keep_independent_hashes(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=java(root,'demo.A','package demo; class A {}')
            p.with_suffix('.class').write_bytes(b'\xca\xfe\xba\xbe\x00\x00\x00\x34\x00\x01')
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],profile(root))
            self.assertEqual({x['kind'] for x in d['files']},{'source','compiled_copy'})
            self.assertEqual(len(d['registrations'][0]['file_keys']),2)

    def test_keyword_string_literal_does_not_change_package_or_hide_dependency(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);java(root,'demo.A','package demo; class A {String marker="package"; B b;}');java(root,'demo.B','package demo; class B {}')
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],profile(root))
            self.assertEqual({x['class_name'] for x in d['files']},{'demo.A','demo.B'})
    def test_fully_qualified_and_used_static_import_dependencies_are_followed(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);java(root,'demo.A','package demo; import static demo.util.U.go; class A { Object x(){ new demo.service.S(); return go(); }}')
            java(root,'demo.service.S','package demo.service; class S {}');java(root,'demo.util.U','package demo.util; class U {static Object go(){return null;}}')
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],profile(root))
            self.assertEqual({x['class_name'] for x in d['files']},{'demo.A','demo.service.S','demo.util.U'})
    def test_secret_setters_are_masked_before_source_snippets_are_recorded(self):
        from source_evidence import java_evidence
        d=java_evidence('class A {void run(){client.setPassword("setterPass"); client.setApiKey("setterKey");}}')
        raw=json.dumps(d);self.assertNotIn('setterPass',raw);self.assertNotIn('setterKey',raw)
    def test_string_semicolon_is_a_literal_in_return_expression(self):
        from source_evidence import java_evidence
        self.assertEqual(java_evidence('class A {String run(){return ";";}}')['returns'][0]['expression'],'";"')
    def test_unreadable_constant_pool_and_unicode_escape_syntax_keep_frontier(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=java(root,'demo.A',r'package demo; class A { Object a=new \u0042(); }');p.with_suffix('.class').write_bytes(b'not a class')
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],profile(root))
            self.assertFalse(d['closed']);self.assertEqual({x['reason'] for x in d['frontier']},{'java_lexical_unsupported','class_constant_pool_unreadable'})

    def test_multiline_secret_setter_preserves_lines_of_later_evidence(self):
        from source_evidence import java_evidence,sanitize_text
        raw='class A {\nvoid run(){\nclient.setPassword(\n"multiSecret"\n);\nmap.get("after");\n}\n}'
        clean=sanitize_text(raw);self.assertEqual(clean.count('\n'),raw.count('\n'))
        item=java_evidence(raw)['field_accesses'][0]
        self.assertEqual(item['line'],6);self.assertIn('map.get',item['snippet']);self.assertNotIn('multiSecret',clean)

    def test_capture_command_records_input_profile_hashes_and_is_immutable(self):
        from source_evidence import capture_sources
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);root=base/'src';java(root,'demo.A','package demo; class A {}')
            inp=base/'input.json';pr=base/'profile.json';out=base/'out'/'capture.json'
            inp.write_text(json.dumps({'business_rows_read':0,'tables':{'actionsetting':[{'id':1,'actionclass':'demo.A'}]}}),'utf-8')
            pr.write_text(json.dumps(profile(root)),'utf-8')
            d=capture_sources(inp,pr,out)
            self.assertEqual(d['status'],'captured');self.assertTrue(d['two_reads_equal'])
            self.assertEqual(len(d['input_sha256']),64);self.assertEqual(len(d['profile_sha256']),64)
            content=out.read_bytes()
            with self.assertRaises(FileExistsError):capture_sources(inp,pr,out)
            self.assertEqual(out.read_bytes(),content)
    def test_capture_rejects_business_input_or_writing_inside_source_roots(self):
        from source_evidence import capture_sources
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);root=base/'src';root.mkdir();inp=base/'input.json';pr=base/'profile.json';out=base/'capture.json'
            inp.write_text(json.dumps({'business_rows_read':1,'tables':{'actionsetting':[]}}),'utf-8');pr.write_text(json.dumps(profile(root)),'utf-8')
            with self.assertRaises(ValueError):capture_sources(inp,pr,out)
            self.assertFalse(out.exists())
            inp.write_text(json.dumps({'business_rows_read':0,'tables':{'actionsetting':[]}}),'utf-8')
            with self.assertRaises(ValueError):capture_sources(inp,pr,root/'capture.json')
    def test_capture_keeps_incomplete_frontier_without_success_claim(self):
        from source_evidence import capture_sources
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);root=base/'src';java(root,'demo.A','package demo; class A { B b;}');java(root,'demo.B','package demo; class B {}')
            inp=base/'input.json';pr=base/'profile.json';out=base/'capture.json';setting=profile(root);setting['limits']['max_depth']=0
            inp.write_text(json.dumps({'business_rows_read':0,'tables':{'actionsetting':[{'id':1,'actionclass':'demo.A'}]}}),'utf-8');pr.write_text(json.dumps(setting),'utf-8')
            d=capture_sources(inp,pr,out)
            self.assertEqual(d['status'],'incomplete');self.assertFalse(d['evidence']['closed'])

    def test_lowercase_java_types_and_fully_qualified_constructors_remain_candidates(self):
        from source_evidence import scan_sources
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);java(root,'demo.A','package demo; class A { helper h; Object run(){return new demo.service.worker();}}')
            java(root,'demo.helper','package demo; class helper {}');java(root,'demo.service.worker','package demo.service; class worker {}')
            d=scan_sources([{'id':1,'actionclass':'demo.A'}],profile(root))
            self.assertEqual({x['class_name'] for x in d['files']},{'demo.A','demo.helper','demo.service.worker'})

    def test_escaped_json_secret_inside_java_literal_is_not_exported_in_snippets(self):
        from source_evidence import java_evidence
        d=java_evidence(r'class A {void run(){String config="{\"password\":\"escapedSecret\",\"name\":\"sample\"}";}}')
        self.assertNotIn('escapedSecret',json.dumps(d))

    def test_literal_receiver_never_exports_raw_json_or_url_credentials(self):
        from source_evidence import java_evidence
        d=java_evidence(r'class A {void run(){ "{\"password\":\"receiverSecret\"}".getBytes(); }}')
        self.assertNotIn('receiverSecret',json.dumps(d))
        call=next(x for x in d['calls'] if x['name']=='getBytes')
        self.assertIsNone(call['receiver'])
    def test_invalid_import_literal_is_not_exported_as_a_package_name(self):
        from source_evidence import java_evidence
        d=java_evidence(r'package demo; import "{\"password\":\"importSecret\"}"; class A {}')
        self.assertNotIn('importSecret',json.dumps(d));self.assertIn('unparsed_package_or_import',d['warnings'])
