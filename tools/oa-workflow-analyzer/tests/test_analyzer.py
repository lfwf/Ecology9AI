import json
import os
from pathlib import Path
import tempfile
import unittest

from fixtures import write_export
try:
    from oa_workflow_analyzer.analyzer import analyze_export
except ImportError:
    analyze_export = None


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(analyze_export, "Analysis orchestration is not implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_variable_counts_and_deterministic_no_side_effect_api(self):
        source = write_export(self.root)
        before = source.read_bytes()
        first = analyze_export(source)
        self.assertEqual(first, analyze_export(source))
        self.assertEqual(first["summary"]["node_count"], 2)
        self.assertEqual(first["summary"]["field_count"], 1)
        self.assertEqual(first["workflows"][0]["links"][0]["condition"], "amount > 0")
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [source])
        json.dumps(first, ensure_ascii=False)

    def test_missing_action_definition_reports_empty_vs_absent(self):
        action = {"id": "a", "workflowid": "900", "objid": "20", "isnode": "1", "type": "3", "customervalue": "1", "ispreadd": "1"}
        result = analyze_export(write_export(self.root, extra={"workflow_addinoperate": [action], "workflowactionset": []}))
        gap = next(g for g in result["gaps"] if g["code"] == "EXTERNAL_ACTION_DEFINITION")
        self.assertIn("为空", gap["reason"])
        self.assertIn("workflowactionset", gap["needed"])
        self.assertIn("20", gap["scope"])
        self.assertTrue(gap["source_refs"])
        self.assertNotIn("接口编号1", gap["reason"])

    def test_decoded_script_channels_deduplicated_and_callbacks_traced(self):
        script = '<script>function push(){jQuery.ajax({url:"/api/test/push"});} WfForm.registerCheckEvent(WfForm.OPER_SAVE,function(cb){push();cb();});</script>'
        result = analyze_export(write_export(self.root, script=script))
        self.assertEqual(len(result["scripts"]), 1)
        event = result["scripts"][0]["analysis"]["events"][0]
        self.assertIn("/api/test/push", event["reachable_endpoints"])
        gap = next(g for g in result["gaps"] if g["code"] == "EXTERNAL_ENDPOINT_IMPLEMENTATION")
        self.assertIn("/api/test/push", gap["needed"])

    def test_inactive_script_not_reported_as_current_network_dependency(self):
        result = analyze_export(write_export(self.root, script='fetch("/api/old");', active="0"))
        self.assertFalse(result["scripts"][0]["active"])
        self.assertFalse(any(g["code"] == "EXTERNAL_ENDPOINT_IMPLEMENTATION" for g in result["gaps"]))

    def test_unknown_configuration_and_dangling_reference_are_explicit(self):
        result = analyze_export(write_export(self.root, extra={"workflow_new_feature": [{"id": "z", "setting": "unknown"}],
                                                               "workflow_nodelink": [{"id": "broken", "workflowid": "900", "nodeid": "10", "destnodeid": "absent"}]}))
        self.assertIn("UNSUPPORTED_CONFIGURATION", [g["code"] for g in result["gaps"]])
        self.assertTrue(any("absent" in g["reason"] or "absent" in g["needed"] for g in result["gaps"]))
        self.assertEqual(result["summary"]["status"], "partial")

    def test_evidence_and_scripts_do_not_leak_obvious_credentials(self):
        source = write_export(self.root, script='const password="super-secret";fetch("/api/x");')
        text = json.dumps(analyze_export(source), ensure_ascii=False)
        self.assertNotIn("super-secret", text)

    def test_every_gap_has_collection_instructions_and_valid_refs(self):
        result = analyze_export(write_export(self.root))
        refs = {x["id"] for x in result["evidence"]}
        self.assertTrue(any(g["category"] == "runtime" for g in result["gaps"]))
        for gap in result["gaps"]:
            for field in ("id", "code", "category", "severity", "scope", "title", "reason", "needed", "how_to_collect"):
                self.assertTrue(gap[field], field)
            self.assertTrue(set(gap["source_refs"]) <= refs)

    @unittest.skipUnless(os.environ.get("OA_WORKFLOW_SAMPLE"), "Local real export is optional")
    def test_real_export_full_regression(self):
        result = analyze_export(os.environ["OA_WORKFLOW_SAMPLE"])
        flow = result["workflows"][0]
        self.assertEqual((len(flow["nodes"]), len(flow["links"]), len(flow["fields"])), (4, 3, 47))
        self.assertEqual(len(flow["formulas"]), 3)
        self.assertEqual(len(flow["linkages"]), 3)
        self.assertEqual(sum(x["enabled"] is True for x in flow["data_inputs"]), 2)
        self.assertEqual(sum(x["enabled"] is False for x in flow["data_inputs"]), 1)
        endpoints = {url for script in result["scripts"] if script["active"] for event in script["analysis"]["events"] for url in event["reachable_endpoints"]}
        self.assertIn("/api/example-project/PurchaseCancelReasonWeb/push", endpoints)
        self.assertIn("EXTERNAL_ACTION_DEFINITION", [x["code"] for x in result["gaps"]])


if __name__ == "__main__":
    unittest.main()
