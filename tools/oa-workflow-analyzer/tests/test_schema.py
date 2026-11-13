"""Versioned interchange contract; jsonschema is an optional test dependency."""
from copy import deepcopy
from importlib import resources
import json
import os
from pathlib import Path
import tempfile
import unittest

from fixtures import write_export
from oa_workflow_analyzer import analyze_export

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


class SchemaResourceTests(unittest.TestCase):
    def test_schema_is_a_bundled_versioned_resource(self):
        resource = resources.files("oa_workflow_analyzer").joinpath("schemas/workflow.schema.json")
        self.assertTrue(resource.is_file(), "The reusable JSON result needs a packaged schema")
        schema = json.loads(resource.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0")


@unittest.skipUnless(Draft202012Validator, "Install jsonschema to validate the interchange contract")
class SchemaValidationTests(unittest.TestCase):
    def setUp(self):
        resource = resources.files("oa_workflow_analyzer").joinpath("schemas/workflow.schema.json")
        self.assertTrue(resource.is_file(), "The reusable JSON result needs a packaged schema")
        self.schema = json.loads(resource.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.result = analyze_export(write_export(
            self.root,
            script='function push(){if (true){WfForm.changeFieldValue("field7",{value:"1"});fetch("/api/test");}} '
                   'WfForm.registerCheckEvent(WfForm.OPER_SAVE,function(cb){push();cb();});',
        ))

    def assert_valid(self, value):
        errors = sorted(self.validator.iter_errors(value), key=lambda error: str(list(error.path)))
        self.assertFalse(errors, "\n".join(f"{list(error.path)}: {error.message}" for error in errors[:10]))

    def test_synthetic_export_matches_the_contract(self):
        self.assert_valid(self.result)

    def test_different_topology_and_unrecognized_enums_do_not_require_a_new_schema(self):
        value = analyze_export(write_export(self.root, extra={
            "workflow_flownode": [
                {"workflowid": "900", "nodeid": "a", "nodetype": "0"},
                {"workflowid": "900", "nodeid": "b", "nodetype": "999"},
                {"workflowid": "900", "nodeid": "c", "nodetype": "3"},
            ],
            "workflow_nodebase": [{"id": node, "nodename": node} for node in "abc"],
            "workflow_nodelink": [
                {"id": "ab", "workflowid": "900", "nodeid": "a", "destnodeid": "b"},
                {"id": "ac", "workflowid": "900", "nodeid": "a", "destnodeid": "c"},
                {"id": "ba", "workflowid": "900", "nodeid": "b", "destnodeid": "a", "isreject": "1"},
            ],
            "workflow_nodeform": [],
        }))
        self.assert_valid(value)
        self.assertEqual(value["summary"]["node_count"], 3)
        self.assertEqual(value["summary"]["link_count"], 3)
        self.assertEqual(value["workflows"][0]["nodes"][1]["type"], "999")
        self.assertTrue(all(item["base_permission"] == "missing" for item in value["workflows"][0]["permissions"]))

    def test_all_public_root_sections_are_required(self):
        for section in ("schema_version", "analyzer", "source", "workflows", "table_inventory",
                        "evidence", "scripts", "gaps", "summary"):
            with self.subTest(section=section):
                value = deepcopy(self.result)
                del value[section]
                self.assertFalse(self.validator.is_valid(value))

    def test_rejects_another_schema_version_or_runtime_verification_claim(self):
        value = deepcopy(self.result)
        value["schema_version"] = "2.0"
        self.assertFalse(self.validator.is_valid(value))
        value = deepcopy(self.result)
        value["analyzer"]["runtime_verified"] = True
        self.assertFalse(self.validator.is_valid(value))

    def test_source_requires_real_sha256_and_nonnegative_sizes(self):
        for key, invalid in (("sha256", "short"), ("xml_sha256", "g" * 64), ("size_bytes", -1)):
            with self.subTest(key=key):
                value = deepcopy(self.result)
                value["source"][key] = invalid
                self.assertFalse(self.validator.is_valid(value))

    def test_normalized_identifiers_remain_strings(self):
        for path in (("nodes", "id"), ("links", "from_node"), ("fields", "id"),
                     ("permissions", "node_id")):
            with self.subTest(path=path):
                value = deepcopy(self.result)
                value["workflows"][0][path[0]][0][path[1]] = 10
                self.assertFalse(self.validator.is_valid(value))

    def test_workflow_sections_and_field_semantics_are_required(self):
        for section in ("nodes", "links", "fields", "permissions", "detail_permissions", "operator_groups",
                        "options", "formulas", "linkages", "data_inputs", "actions", "layouts",
                        "code_rules", "withdrawal", "source_refs", "issues"):
            with self.subTest(section=section):
                value = deepcopy(self.result)
                del value["workflows"][0][section]
                self.assertFalse(self.validator.is_valid(value))
        value = deepcopy(self.result)
        del value["workflows"][0]["fields"][0]["detail"]
        self.assertFalse(self.validator.is_valid(value))

    def test_unknown_permissions_and_layout_state_stay_nullable(self):
        value = deepcopy(self.result)
        permission = value["workflows"][0]["permissions"][0]
        permission.update(view=None, edit=None, mandatory=None, manual_edit_prohibited=None,
                          base_permission="missing")
        value["workflows"][0]["layouts"][0]["active"] = None
        value["scripts"][0]["active"] = None
        self.assert_valid(value)
        permission["view"] = "0"
        self.assertFalse(self.validator.is_valid(value))

    def test_gap_requires_actionable_collection_details_and_known_category(self):
        for key in ("code", "scope", "title", "reason", "needed", "how_to_collect", "source_refs"):
            with self.subTest(key=key):
                value = deepcopy(self.result)
                del value["gaps"][0][key]
                self.assertFalse(self.validator.is_valid(value))
        value = deepcopy(self.result)
        value["gaps"][0]["category"] = "verified"
        self.assertFalse(self.validator.is_valid(value))
        value["gaps"][0]["category"] = "missing"
        value["gaps"][0]["how_to_collect"] = ""
        self.assertFalse(self.validator.is_valid(value))

    def test_evidence_and_script_findings_keep_provenance(self):
        for mutate in (
            lambda r: r["evidence"][0].update(id="not-an-evidence-id"),
            lambda r: r["evidence"][0].update(line=0),
            lambda r: r["evidence"][0]["values"].update(id=123),
            lambda r: r["scripts"][0]["analysis"]["events"][0].pop("endpoint_paths"),
            lambda r: r["scripts"][0]["analysis"]["network_calls"][0].update(line=0),
            lambda r: r["workflows"][0]["fields"][0].update(source_refs=["wrong"]),
        ):
            value = deepcopy(self.result)
            mutate(value)
            self.assertFalse(self.validator.is_valid(value))

    def test_dynamic_urls_and_unsupported_script_encoding_are_valid_partial_results(self):
        for script in ('fetch(base + "/resource");', "encrypted:unknown"):
            with self.subTest(script=script):
                value = analyze_export(write_export(self.root, script=script))
                self.assert_valid(value)
                self.assertEqual(value["summary"]["status"], "partial")

    def test_new_optional_fields_and_raw_unknown_values_are_forward_compatible(self):
        value = deepcopy(self.result)
        value["future_summary"] = {"detail": "extension"}
        value["workflows"][0]["fields"][0]["future_property"] = [1, None]
        value["workflows"][0]["raw"]["new_platform_flag"] = "unknown-new-value"
        self.assert_valid(value)

    def test_summary_cannot_claim_live_status_or_negative_counts(self):
        value = deepcopy(self.result)
        value["summary"]["status"] = "live_verified"
        self.assertFalse(self.validator.is_valid(value))
        value["summary"]["status"] = "parsed"
        value["summary"]["field_count"] = -1
        self.assertFalse(self.validator.is_valid(value))

    @unittest.skipUnless(os.environ.get("OA_WORKFLOW_SAMPLE"), "Local real export is optional")
    def test_original_export_matches_schema_without_modification(self):
        source = Path(os.environ["OA_WORKFLOW_SAMPLE"])
        before = source.read_bytes()
        value = analyze_export(source)
        self.assert_valid(value)
        self.assertEqual((value["summary"]["workflow_count"], value["summary"]["node_count"],
                          value["summary"]["field_count"]), (1, 4, 47))
        evidence_ids = {item["id"] for item in value["evidence"]}
        self.assertEqual(len(evidence_ids), len(value["evidence"]))

        def check_refs(item):
            if isinstance(item, dict):
                if "source_refs" in item:
                    self.assertTrue(set(item["source_refs"]) <= evidence_ids)
                for child in item.values():
                    check_refs(child)
            elif isinstance(item, list):
                for child in item:
                    check_refs(child)

        check_refs(value)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
