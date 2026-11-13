"""Synthetic, non-executing tests for layout script evidence."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from oa_workflow_analyzer.scripts import analyze_script, decode_layout_text, sanitize_script


def encrypted(text, encoding="utf-8"):
    data = text.encode(encoding)
    pad = 16 - len(data) % 16
    enc = Cipher(algorithms.AES(b"WEAVER E-DESIGN."), modes.CBC(b"weaver e-design.")).encryptor()
    return (enc.update(data + bytes([pad]) * pad) + enc.finalize()).hex()


class DecodeTests(unittest.TestCase):
    def test_plain_and_empty_preserve_source_lines(self):
        source = '<script>\r\nconst a = "中文";\r\n</script>\r\n'
        result = decode_layout_text(source)
        self.assertEqual(result["status"], "plain")
        self.assertEqual(result["text"], source)
        self.assertEqual(result["input_sha256"], hashlib.sha256(source.encode()).hexdigest())
        for source in ("", " \n", "<script>\n</script>\n", "<script type='text/javascript'> /* no code */ </script>"):
            self.assertEqual(decode_layout_text(source)["status"], "empty")

    def test_e_design_utf8_gb18030_and_encoded_empty(self):
        for encoding in ("utf-8", "gb18030"):
            source = '<script>\nvar name="采购";\n</script>'
            result = decode_layout_text(encrypted(source, encoding))
            self.assertEqual(result["status"], "decoded")
            self.assertEqual(result["text"], source)
            self.assertEqual(result["encoding"], encoding)
            self.assertEqual(result["decoded_bytes_sha256"], hashlib.sha256(source.encode(encoding)).hexdigest())
        self.assertEqual(decode_layout_text(encrypted("<script></script>"))["status"], "empty")

    def test_unknown_encoding_invalid_padding_and_length_remain_visible(self):
        for source in ("ENC:unknown:ciphertext", "ff" * 16, "a0" * 15, "deadbee"):
            result = decode_layout_text(source)
            self.assertEqual(result["status"], "unsupported", source)
            self.assertTrue(result["error"])
            self.assertEqual(result["text"], "")


class StaticScriptTests(unittest.TestCase):
    def test_save_submit_follow_local_helper_paths(self):
        source = '''<script>
WfForm.registerCheckEvent(WfForm.OPER_SAVE, function (callback) { pushSap(); });
WfForm.registerCheckEvent(WfForm.OPER_SUBMIT, function (callback) { validateAndPush(); });
function validateAndPush() { return pushSap(); }
function pushSap() { return jQuery.ajax({url: "/api/example-project/PurchaseCancelReasonWeb/push", type: "POST"}); }
</script>'''
        result = analyze_script(source)
        self.assertEqual(len(result["events"]), 2)
        url = "/api/example-project/PurchaseCancelReasonWeb/push"
        self.assertEqual(result["events"][0]["reachable_endpoints"], [url])
        self.assertEqual(result["events"][1]["reachable_endpoints"], [url])
        self.assertEqual(result["events"][1]["endpoint_paths"][0]["path"], ["WfForm.OPER_SUBMIT", "validateAndPush", "pushSap"])
        self.assertEqual(result["network_calls"][0]["function"], "pushSap")
        self.assertEqual(result["network_calls"][0]["line"], 5)

    def test_comments_and_string_braces_do_not_create_findings(self):
        source = '''// WfForm.registerCheckEvent(WfForm.OPER_DELETE, function(){fetch("/disabled")});
/* $.ajax({url:"/also-disabled"}); */
var explanation = 'fetch("/fake") } /* //';
WfForm.registerCheckEvent(WfForm.OPER_SUBMIT, function () {
  const weird = "} // /*";
  if (value === "/* } //") { fetch("/active"); }
});'''
        result = analyze_script(source)
        self.assertEqual([e["operation"] for e in result["events"]], ["WfForm.OPER_SUBMIT"])
        self.assertEqual([n["url"] for n in result["network_calls"]], ["/active"])
        self.assertEqual(result["conditions"][0]["text"], 'value === "/* } //"')
        self.assertEqual(result["conditions"][0]["line"], 6)
        self.assertEqual(result["events"][0]["reachable_endpoints"], ["/active"])

    def test_field_expressions_attrs_and_conditions_have_source_lines(self):
        source = '''const field = WfForm.convertFieldNameToId("amount");
if (count > 0 && mode !== "2") {
  WfForm.changeFieldValue(field + "_" + rowIndex, {value: amount});
  WfForm.changeFieldAttr("field123_" + rowIndex, 1);
}'''
        result = analyze_script(source)
        self.assertEqual(result["field_writes"][0]["target"], 'field + "_" + rowIndex')
        self.assertEqual(result["field_writes"][0]["value"], "{value: amount}")
        self.assertEqual(result["field_writes"][0]["line"], 3)
        self.assertEqual(result["attribute_changes"][0]["attribute"], "1")
        self.assertEqual(result["attribute_changes"][0]["line"], 4)
        self.assertEqual(result["conditions"][0]["text"], 'count > 0 && mode !== "2"')

    def test_named_callbacks_arrow_helpers_dynamic_endpoints_and_recursion(self):
        source = '''const call = () => { recur(); fetch(base + "/push"); };
function recur() { if (x) { call(); } }
WfForm.registerCheckEvent(WfForm.OPER_SAVE + "," + WfForm.OPER_SUBMIT, call);'''
        result = analyze_script(source)
        self.assertEqual(result["events"][0]["operations"], ["save", "submit"])
        self.assertEqual(result["events"][0]["calls"], ["call"])
        self.assertEqual(result["events"][0]["reachable_endpoints"], [])
        self.assertIsNone(result["network_calls"][0]["url"])
        self.assertTrue(any(w["code"] == "DYNAMIC_ENDPOINT" for w in result["warnings"]))

    def test_dormant_nested_function_is_not_reported_reachable(self):
        source = '''function helper() { function dormant() { fetch("/dormant"); } }
WfForm.registerCheckEvent(WfForm.OPER_SAVE, function () { helper(); });'''
        self.assertEqual(analyze_script(source)["events"][0]["reachable_endpoints"], [])

    def test_regex_after_control_condition_is_not_code(self):
        source = '''if (ready) /fetch("fake")/.test(text);
WfForm.registerCheckEvent(WfForm.OPER_SAVE, () => { fetch("/real"); });'''
        result = analyze_script(source)
        self.assertEqual([n["url"] for n in result["network_calls"]], ["/real"])

    def test_regex_statements_and_division_keep_distinct_evidence(self):
        source = '''if (ready) {} /fetch("fake")/.test(text);
if (ready) { /fetch("also-fake")/.test(text); }
const ratio = total / count;
fetch("/real");'''
        result = analyze_script(source)
        self.assertEqual([n["url"] for n in result["network_calls"]], ["/real"])

    def test_ajax_uses_only_top_level_url_property(self):
        result = analyze_script('$.ajax({data: {url: "/data"}, url: "/real"});')
        self.assertEqual([n["url"] for n in result["network_calls"]], ["/real"])
        result = analyze_script('$.ajax({data: {url: "/data"}});')
        self.assertIsNone(result["network_calls"][0]["url"])

    def test_commented_or_quoted_xhr_declaration_is_not_network_evidence(self):
        for declaration in ('// var req = new XMLHttpRequest();',
                            'const text = "var req = new XMLHttpRequest();";'):
            result = analyze_script(declaration + '\nreq.open("GET", "/unproven");')
            self.assertEqual(result["network_calls"], [])
        result = analyze_script('var req = new XMLHttpRequest(); req.open("GET", "/real");')
        self.assertEqual([n["url"] for n in result["network_calls"]], ["/real"])

    def test_nested_uninvoked_callbacks_are_not_event_paths(self):
        source = '''function send() {
  const dormant = {run: function () { fetch("/dormant"); }};
  const later = () => fetch("/later");
  return new Promise(function (resolve) { fetch("/promise"); resolve(); });
}
WfForm.registerCheckEvent(WfForm.OPER_SAVE, function () { send(); });'''
        result = analyze_script(source)
        self.assertEqual(result["events"][0]["reachable_endpoints"], ["/promise"])
        self.assertTrue(any(w["code"] == "UNFOLLOWED_CALLBACK" for w in result["warnings"]))

    def test_dynamic_templates_warn_without_exposing_literal_source(self):
        result = analyze_script('const info = `fetch("/fake") ${fetch("/dynamic")}`; fetch(`/real`);')
        self.assertEqual([n["url"] for n in result["network_calls"]], ["/real"])
        self.assertTrue(any(w["code"] == "DYNAMIC_TEMPLATE" for w in result["warnings"]))

    def test_event_operation_names_in_strings_and_comments_are_inert(self):
        source = '''WfForm.registerCheckEvent("WfForm.OPER_DELETE", function () {});
WfForm.registerCheckEvent(WfForm.OPER_SAVE /* WfForm.OPER_SUBMIT */, function () {});'''
        result = analyze_script(source)
        self.assertEqual(result["events"][0]["operations"], [])
        self.assertEqual(result["events"][1]["operations"], ["save"])

    def test_sanitize_header_setters_and_bracket_assignments(self):
        source = '''headers["Authorization"] = "Bearer bracket-secret";
xhr.setRequestHeader("Authorization", "Bearer header-secret");
const token = "ordinary-secret";
fetch("/keep");'''
        result = sanitize_script(source)
        for secret in ("bracket-secret", "header-secret", "ordinary-secret"):
            self.assertNotIn(secret, result)
        self.assertEqual(result.count("\n"), source.count("\n"))
        self.assertIn('fetch("/keep")', result)

    def test_source_is_data_and_dynamic_execution_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "must-not-exist.txt"
            source = 'eval("write file ' + str(marker).replace("\\", "\\\\") + '"); new Function("fetch(\'/bad\')");'
            result = analyze_script(source)
            self.assertFalse(marker.exists())
            self.assertEqual(result["network_calls"], [])
            self.assertTrue(any(w["code"] == "DYNAMIC_CODE" for w in result["warnings"]))

    def test_html_non_script_content_not_read_as_active_js(self):
        source = '<div>fetch("/text")</div>\n<script>fetch("/code")</script>'
        result = analyze_script(source)
        self.assertEqual([n["url"] for n in result["network_calls"]], ["/code"])
        self.assertEqual(result["network_calls"][0]["line"], 2)

    def test_sanitize_credentials_preserves_lines_and_useful_evidence(self):
        source = '''const password = "supersecret";
const token = 'tok-123';
fetch("/api/push", {headers: {"Authorization": "Bearer abc", ordinary: "keep"}});
const client_secret = `literal-secret`;
WfForm.changeFieldValue("field123", {value: 2});'''
        result = sanitize_script(source)
        for secret in ("supersecret", "tok-123", "Bearer abc", "literal-secret"):
            self.assertNotIn(secret, result)
        self.assertEqual(result.count("\n"), source.count("\n"))
        self.assertIn('fetch("/api/push"', result)
        self.assertIn('ordinary: "keep"', result)
        self.assertIn('"field123"', result)


if __name__ == "__main__":
    unittest.main()
