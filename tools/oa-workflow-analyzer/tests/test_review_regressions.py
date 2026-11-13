"""Independent review regressions; all source data here is synthetic."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from fixtures import export_bytes, write_export
from oa_workflow_analyzer.analyzer import analyze_export
from oa_workflow_analyzer.cli import _publish, main


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_obvious_credentials_redacted_from_raw_values(self):
        credentials = {name: name + "-review-secret" for name in
                       ("token", "pwd", "api_key", "client_secret", "refresh_token")}
        source = write_export(self.root, extra={"workflow_new_config": [credentials]})
        result = json.dumps(analyze_export(source), ensure_ascii=False)
        for secret in credentials.values():
            with self.subTest(secret=secret):
                self.assertFalse(secret in result, "Raw sensitive field value escaped redaction")

    def test_obvious_credentials_redacted_from_export_metadata(self):
        document = ElementTree.fromstring(export_bytes())
        document.find("ELEMENT").set("TOKEN", "metadata-review-secret")
        document.find("ELEMENT/TABLE").set("PASSWORD", "table-review-secret")
        source = self.root / "metadata.xml"
        source.write_bytes(ElementTree.tostring(document, encoding="utf-8"))
        result = json.dumps(analyze_export(source), ensure_ascii=False)
        self.assertFalse("metadata-review-secret" in result, "ELEMENT metadata escaped redaction")
        self.assertFalse("table-review-secret" in result, "TABLE metadata escaped redaction")

    def test_script_active_flag_agrees_with_normalized_layout(self):
        source = write_export(self.root, script='fetch("/active");', active="Y")
        result = analyze_export(source)
        self.assertIs(result["workflows"][0]["layouts"][0]["active"], True)
        self.assertIs(result["scripts"][0]["active"], True)
        self.assertIn("EXTERNAL_ENDPOINT_IMPLEMENTATION", [g["code"] for g in result["gaps"]])

    def test_unknown_script_active_flag_stays_unknown(self):
        result = analyze_export(write_export(self.root, script='fetch("/unknown");', active="99"))
        self.assertIsNone(result["workflows"][0]["layouts"][0]["active"])
        self.assertIsNone(result["scripts"][0]["active"])

    def test_non_object_manifest_invalidates_cache_without_aborting(self):
        source = write_export(self.root)
        analysis = analyze_export(source)
        output = self.root / "out"
        first = _publish(analysis, output, source, False)
        original = Path(first["output_dir"])
        (original / "manifest.json").write_text("[]", encoding="utf-8")
        second = _publish(analysis, output, source, False)
        self.assertNotEqual(second["output_dir"], str(original))
        self.assertEqual((original / "manifest.json").read_text(encoding="utf-8"), "[]")

    def test_unreadable_input_directory_does_not_cancel_valid_file(self):
        blocked = self.root / "unreadable"
        blocked.mkdir()
        source = write_export(self.root)
        original_iterdir = Path.iterdir

        def inaccessible(path):
            if path == blocked:
                raise PermissionError("Synthetic directory enumeration denial")
            return original_iterdir(path)

        stdout = StringIO()
        with patch.object(Path, "iterdir", inaccessible), redirect_stdout(stdout):
            code = main([str(blocked), str(source), "--output", str(self.root / "out")])
        self.assertEqual(code, 1)
        summary = json.loads(stdout.getvalue())
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["failed"], 1)

    def test_named_data_source_is_an_explicit_external_dependency(self):
        source = write_export(self.root, extra={
            "workflow_datainput_entry": [{"id": "entry", "workflowid": "900", "enable": "0"}],
            "workflow_datainput_main": [{"id": "query", "entryid": "entry", "datasourcename": "remote_sap_readonly"}],
        })
        result = analyze_export(source)
        self.assertTrue(any("remote_sap_readonly" in g["reason"] or "remote_sap_readonly" in g["needed"]
                            for g in result["gaps"]))

    def test_unrelated_browser_text_cannot_resolve_browser_definition(self):
        source = write_export(self.root, extra={
            "workflow_billfield": [{"id": "7", "billid": "-80", "fieldname": "customer", "fielddbtype": "browser.customerLookup"}],
            "workflow_browdef": [{"id": "otherLookup", "description": "customerLookup", "sql": "select id from unrelated"}],
        })
        result = analyze_export(source)
        self.assertIn("BROWSER_DEFINITION", [g["code"] for g in result["gaps"]])

    def test_disabled_action_row_does_not_resolve_required_action(self):
        source = write_export(self.root, extra={
            "workflow_addinoperate": [{"id": "action", "workflowid": "900", "objid": "20", "isnode": "1", "type": "3", "customervalue": "1", "ispreadd": "1"}],
            "workflowactionset": [{"workflowid": "900", "nodeid": "20", "isused": "0"}],
        })
        result = analyze_export(source)
        self.assertTrue(any("ACTION" in g["code"] for g in result["gaps"]))


if __name__ == "__main__":
    unittest.main()
