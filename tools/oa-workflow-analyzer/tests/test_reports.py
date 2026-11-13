"""Behavioral report tests using synthetic normalized exports only."""
import builtins
from copy import deepcopy
from hashlib import sha256
import importlib.util
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


REPORTS_FILE = Path(__file__).resolve().parents[1] / "src/oa_workflow_analyzer/reports.py"


def example_result():
    return {
        "schema_version": "1.0",
        "analyzer": {"name": "oa-workflow-analyzer", "version": "0.1", "profile": "e9-local-v1"},
        "source": {"name": "测试流程.wewf", "sha256": "abc123", "encoding": "gbk"},
        "summary": {"workflow_count": 2, "node_count": 3, "status": "partial"},
        "workflows": [
            {
                "id": "w1", "name": "物料申请", "form_id": "-8", "source_refs": ["ev001"],
                "nodes": [{"id": "a", "name": "开始", "type": "0", "type_name": "创建", "source_refs": ["ev002"]},
                          {"id": "b", "name": "审批", "type": "88", "type_name": "未知", "source_refs": ["ev003"]}],
                "links": [{"id": "l1", "from_node": "a", "to_node": "b", "name": "同意", "condition": "amount > 7", "is_reject": False, "source_refs": ["ev004"]}],
                "fields": [{"id": "f1", "name": "stock", "label": "库存余额", "table": "main", "db_type": "int", "detail": False, "source_refs": ["ev005"]}],
                "permissions": [{"node_id": "a", "field_id": "f1", "view": True, "edit": True, "mandatory": False, "manual_edit_prohibited": True, "base_permission": "编辑", "source_refs": ["ev006"]}],
                "detail_permissions": [{"node_id": "a", "detail_id": "1", "add": True, "delete": False, "source_refs": ["ev007"]}],
                "operator_groups": [{"id": "g1", "node_id": "b", "name": "审批人", "rules": [{"type": "5", "objid": "f1", "signorder": "1"}], "source_refs": ["ev008"]}],
                "options": [{"field_id": "f1", "value": "0", "label": "否", "source_refs": ["ev009"]}],
                "formulas": [{"id": "f2", "formula": "[main.f1]=SourceValue()", "trigger": "load", "source_refs": ["ev010"]}],
                "linkages": [{"id": "v1", "condition": "state=4", "target_field": "f1", "stored_attribute": "2", "source_refs": ["ev011"]}],
                "data_inputs": [{"id": "d1", "name": "带入物料", "enabled": False, "trigger_field": "f1", "mappings": [{"from": "amount", "to": "f1"}], "source_refs": ["ev012"]}],
                "actions": [{"id": "ac1", "node_id": "b", "raw": {"type": "3", "customervalue": "1"}, "source_refs": ["ev013"]}],
                "layouts": [{"id": "lay1", "node_id": "a", "active": True, "placements": [{"field_id": "f1", "cell": "2,1", "hidden": ["行隐藏"]}], "source_refs": ["ev014"]}],
                "code_rules": [{"prefix": "TEST", "source_refs": ["ev015"]}],
                "withdrawal": [{"remarkrequired": "1", "source_refs": ["ev016"]}],
                "issues": [{"code": "UNKNOWN_NODE_TYPE", "message": "类型88尚未识别", "source_refs": ["ev003"]}],
            },
            {"id": "w2", "name": "出差登记", "nodes": [{"id": "c", "name": "独立节点", "type": "0"}]},
        ],
        "scripts": [{"id": "s1", "node_id": "a", "layout_id": "lay1", "active": True, "source_refs": ["ev014"], "decoding": {"status": "decoded", "encoding": "gb18030"}, "text": "<script>alert('source')</script>", "analysis": {"events": [{"operation": "OPER_SAVE", "line": 7, "reachable_endpoints": ["/api/example/query"]}], "network_calls": [{"url": "/api/example/query", "line": 12}], "warnings": ["动态调用无法静态确认"]}}],
        "gaps": [{"id": "gap1", "code": "EXTERNAL_ACTION", "category": "missing", "severity": "warning", "scope": "w1/b", "title": "接口定义未随包提供", "reason": "仅有标记", "needed": "workflowactionset明细", "how_to_collect": "只读导出节点集成配置", "source_refs": ["ev013"]}],
        "table_inventory": [{"table": "workflowactionset", "count": 0, "present": True, "supported": True}],
        "evidence": [{"id": "ev013", "table": "workflow_addinoperate", "line": 123, "values": {"type": "3"}}],
    }


class ReportTests(unittest.TestCase):
    def reports(self):
        self.assertTrue(REPORTS_FILE.is_file(), "The report module must implement the normalized result contract")
        spec = importlib.util.spec_from_file_location("_reports_under_test", REPORTS_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_markdown_renders_multiple_workflows_and_actual_configuration(self):
        output = self.reports().render_markdown(example_result())
        for text in ("物料申请", "出差登记", "库存余额", "节点字段权限", "明细权限", "操作人", "选项", "SourceValue()", "state=4", "带入物料", "行隐藏", "TEST", "workflowactionset明细", "ev013", "abc123", "e9-local-v1", "OPER_SAVE", "/api/example/query", "gb18030"):
            self.assertIn(text, output)
        self.assertIn("mermaid", output)
        self.assertIn("workflow.json", output)
        self.assertIn("未验证线上", output)
        self.assertIn("部分", output)

    def test_missing_sections_do_not_invent_formulas_or_permission_success(self):
        output = self.reports().render_markdown({"workflows": [{"id": "x", "name": "库存计算", "fields": [{"id": "f", "label": "可用库存"}]}]})
        self.assertIn("可用库存", output)
        self.assertNotIn("## 平台公式", output)
        self.assertNotIn("库存=", output)
        self.assertNotIn("运行成功", output)
        self.assertNotIn("解析完成", output)

    def test_unknown_enum_and_partial_issues_are_kept(self):
        output = self.reports().render_markdown(example_result())
        self.assertIn("88", output)
        self.assertIn("UNKNOWN_NODE_TYPE", output)
        self.assertIn("类型88尚未识别", output)
        self.assertIn("动态调用无法静态确认", output)
        self.assertIn("静态", output)

    def test_mermaid_quotes_metacharacters_and_keeps_stable_safe_node_ids(self):
        result = {"workflows": [{"id": "<bad>", "name": "diagram", "nodes": [{"id": 'a"] --> injected["', "name": '审批"]\nX-->Y <script>'}, {"id": "b", "name": "归档"}], "links": [{"from_node": 'a"] --> injected["', "to_node": "b", "name": '同意|"break'}]}]}
        output = self.reports().render_markdown(result)
        diagram = output.split("```mermaid\n", 1)[1].split("```", 1)[0]
        self.assertNotIn('审批"]', diagram)
        self.assertNotIn("<script>", diagram)
        self.assertNotIn("injected", diagram)
        self.assertIn("-->", diagram)

    def test_html_is_offline_and_escapes_source_and_attributes(self):
        result = example_result()
        result["source"]["name"] = '<img src=x onerror="boom()">'
        result["workflows"][0]["name"] = '<svg onload="evil()">'
        output = self.reports().render_html(result)
        self.assertIn("Content-Security-Policy", output)
        self.assertIn("default-src 'none'", output)
        self.assertIn("script-src 'none'", output)
        self.assertNotIn("<script", output.lower())
        self.assertNotIn("<img", output.lower())
        self.assertNotIn("<svg", output.lower())
        self.assertIn("&lt;script&gt;", output)
        self.assertIn("&lt;svg", output)
        self.assertNotIn("https://", output)
        self.assertIn("@media print", output)

    def test_html_shows_empty_exported_table_separately_from_unknown_support(self):
        result = example_result()
        result["table_inventory"].append({"table": "new_custom_config", "count": 2, "present": True, "supported": False})
        output = self.reports().render_html(result)
        self.assertIn("workflowactionset", output)
        self.assertIn("new_custom_config", output)
        self.assertIn("已导出为空", output)
        self.assertIn("未支持", output)

    def test_pdf_is_real_and_supports_chinese_and_long_source_lines(self):
        reports = self.reports()
        try:
            import reportlab  # noqa: F401
        except ImportError:
            self.skipTest("Optional ReportLab is unavailable")
        result = example_result()
        result["scripts"][0]["text"] += "\n" + "a" * 3000
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "中文说明.pdf"
            self.assertIsNone(reports.render_pdf(result, target))
            data = target.read_bytes()
            self.assertTrue(data.startswith(b"%PDF-"))
            self.assertGreater(len(data), 1000)

    def test_pdf_missing_optional_dependency_has_actionable_error(self):
        reports = self.reports()
        real_import = builtins.__import__

        def missing_reportlab(name, *args, **kwargs):
            if name == "reportlab" or name.startswith("reportlab."):
                raise ImportError("synthetic missing optional dependency")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=missing_reportlab):
            with self.assertRaisesRegex(RuntimeError, "ReportLab|reportlab"):
                reports.render_pdf(example_result(), Path("unused.pdf"))

    def test_record_level_unknowns_and_issues_are_visible_in_both_reports(self):
        result = example_result()
        result["workflows"][0]["fields"][0]["raw"] = {"future_enum": "197"}
        result["workflows"][0]["fields"][0]["issues"] = [{"code": "UNKNOWN_CONTROL", "message": "无法解释控件代码197"}]
        result["workflows"][0]["permissions"][0]["issues"] = [{"code": "UNKNOWN_PERMISSION", "message": "权限未知"}]
        result["workflows"][0]["export_state"] = {"actions": "empty", "code_rules": "absent"}
        for render in (self.reports().render_markdown, self.reports().render_html):
            output = render(result)
            for text in ("197", "UNKNOWN_CONTROL", "UNKNOWN_PERMISSION", "权限未知", "empty", "absent"):
                self.assertIn(text, output)

    def test_html_only_uses_constant_resource_attributes_even_for_nested_raw_input(self):
        result = example_result()
        payload = '<iframe src="https://example.invalid/"></iframe><style>@import "https://example.invalid";</style><a href="javascript:evil()">x</a>'
        result["workflows"][0]["actions"][0]["raw"]["payload"] = payload
        result["workflows"][0]["nodes"][0]["name"] = payload
        result["scripts"][0]["analysis"]["events"][0]["operation"] = payload

        class Tags(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
                self.resources = []

            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)
                self.resources.extend(value for key, value in attrs if key in ("href", "src", "action", "style") or key.startswith("on"))

        output = self.reports().render_html(result)
        parsed = Tags()
        parsed.feed(output)
        self.assertNotIn("iframe", parsed.tags)
        self.assertNotIn("script", parsed.tags)
        self.assertEqual(parsed.resources, ["workflow.json", "evidence.json", "missing-data.json", "agent-context.json", "manifest.json"])
        self.assertIn("&lt;iframe", output)

    def test_markdown_source_cannot_create_links_headings_or_break_source_block(self):
        result = example_result()
        result["workflows"][0]["name"] = "[source](javascript:bad())\n# Heading"
        result["scripts"][0]["text"] = "```\n<script>alert(1)</script>\n```"
        output = self.reports().render_markdown(result)
        self.assertNotIn("[source](javascript", output)
        self.assertNotIn("\n# Heading", output)
        self.assertIn("    ```\n    <script>", output)

    def test_mermaid_graph_is_stable_and_covers_loops_and_missing_nodes(self):
        result = example_result()
        result["workflows"][0]["links"].extend([
            {"from_node": "b", "to_node": "a", "name": "回路"},
            {"from_node": "b", "to_node": "missing", "name": "悬空"},
        ])
        reports = self.reports()
        first = reports.render_markdown(result)
        second = reports.render_markdown(result)
        self.assertEqual(first, second)
        diagram = first.split("```mermaid\n", 1)[1].split("```", 1)[0]
        self.assertEqual(diagram.count("-->"), 3)
        self.assertIn("未导出节点", diagram)

    def test_large_raw_payloads_are_fingerprinted_without_mutating_evidence(self):
        result = example_result()
        payload = "opaque-payload-" * 4000
        result["workflows"][0]["layouts"][0]["raw"] = {"pluginjson": payload, "future_enum": "197"}
        result["evidence"][0]["metadata"] = {"PRIMARYKEY": "id", "PRIMARYKEYVALUE": "42", "SELECT": payload}
        result["evidence"][0]["decodings"] = {"cipher": payload}
        original = deepcopy(result)
        for render in (self.reports().render_markdown, self.reports().render_html):
            output = render(result)
            self.assertNotIn(payload, output)
            self.assertNotIn("opaque-payload-" * 100, output)
            self.assertIn(str(len(payload)), output)
            self.assertIn(sha256(payload.encode("utf-8")).hexdigest(), output)
            self.assertIn("evidence.json", output)
            self.assertIn("197", output)
        self.assertEqual(result, original)

    def test_permission_matrix_covers_all_fields_nodes_and_special_flags(self):
        result = example_result()
        workflow = result["workflows"][0]
        workflow["fields"].append({"id": "f2", "name": "quantity", "label": "申请数量"})
        workflow["permissions"][0]["layouts"] = [{"id": "lay1", "surface": "desktop", "placement": "present", "hidden": ["row"]}]
        workflow["permissions"].extend([
            {"node_id": "b", "field_id": "f1", "base_permission": "readonly", "view": True, "edit": False, "mandatory": False, "source_refs": ["ev017"]},
            {"node_id": "a", "field_id": "f2", "base_permission": "mandatory", "view": True, "edit": True, "mandatory": True, "source_refs": ["ev018"]},
            {"node_id": "b", "field_id": "f2", "base_permission": "missing", "source_refs": ["ev019"]},
            {"node_id": "b", "field_id": "-9", "base_permission": "unknown", "raw": {"future_enum": "987"}, "source_refs": ["ev020"]},
        ])
        for render in (self.reports().render_markdown, self.reports().render_html):
            output = render(result)
            for text in ("节点字段权限矩阵", "开始（a）", "审批（b）", "申请数量", "f2", "-9", "只读", "必填", "缺记录", "禁止手工编辑", "行隐藏", "ev017", "ev018", "ev019", "ev020", "987"):
                self.assertIn(text, output)

    def test_static_conditions_are_summarized_with_structured_trace_paths(self):
        result = example_result()
        result["scripts"][0]["analysis"]["conditions"] = [
            {"kind": "if", "text": f"field_{index} > 0", "line": index + 1, "snippet": f"if (field_{index} > 0)"}
            for index in range(30)
        ]
        result["scripts"][0]["analysis"]["functions"] = [{"name": "loadData", "line": 99, "calls": ["setFields"]}]
        output = self.reports().render_markdown(result)
        self.assertIn("30 条", output)
        self.assertIn("analysis.conditions", output)
        self.assertNotIn("field_29", output)
        self.assertIn("loadData", output)
        self.assertIn("setFields", output)

    def test_main_report_does_not_repeat_all_evidence_and_empty_table_metadata(self):
        result = example_result()
        result["evidence"].extend({"id": f"unused-evidence-{index}", "table": "archive_only", "line": index} for index in range(200))
        result["table_inventory"].extend({"table": f"empty-archive-only-{index}", "count": 0, "present": True, "supported": True} for index in range(100))
        result["table_inventory"].append({"table": "unhandled_rules", "count": 7, "present": True, "supported": False})
        output = self.reports().render_markdown(result)
        self.assertNotIn("unused-evidence-199", output)
        self.assertNotIn("empty-archive-only-99", output)
        self.assertIn("unhandled_rules", output)
        self.assertIn("evidence.json", output)
        self.assertIn("table_inventory", output)


if __name__ == "__main__":
    unittest.main()
