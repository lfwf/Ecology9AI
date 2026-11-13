"""Contract tests built from synthetic exports, with no personnel fixtures."""

import base64
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import zipfile

try:
    from oa_workflow_analyzer.archive import load_export, ParseError, Limits
except ImportError:
    load_export = None
    ParseError = ValueError
    Limits = None


def xml_document(body, encoding="utf-8"):
    return (f'<?xml version="1.0" encoding="{encoding}"?><root>{body}</root>').encode(encoding)


def table(name, value, *, field="name", extra="", attrs=""):
    return f'<ELEMENT ID="x" TABLENAME="{name}"><TABLE ID="x" TABLENAME="{name}" {attrs}><FIELD FIELDNAME="{field}" FIELDVALUE="{value}" {extra}/></TABLE></ELEMENT>'


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(load_export, "Reusable archive parser has not been implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, data, name="流程 有空格.xml"):
        path = self.root / name
        path.write_bytes(data)
        return path

    def zip(self, entries, name="流程.wewf"):
        stream = BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for key, value in entries:
                archive.writestr(key, value)
        return self.write(stream.getvalue(), name)

    def test_gbk_and_arbitrary_node_count(self):
        data = xml_document(table("workflow_base", "任意测试流程", field="workflowname"), "gbk")
        result = load_export(self.zip([("workflow.xml", data)]))
        self.assertEqual(result["tables"]["workflow_base"][0]["values"]["workflowname"], "任意测试流程")
        self.assertEqual(result["source"]["encoding"].lower(), "gbk")
        self.assertEqual(len(result["source"]["sha256"]), 64)

    def test_text_attribute_is_case_insensitive_and_has_line_reference(self):
        data = xml_document('<ELEMENT ID="n" TABLENAME="workflow_base">\n<TABLE TABLENAME="workflow_base"><FIELD FIELDNAME="workflowname" FIELDVALUE="ignored" FIELDTEXT="Y"><![CDATA[测试<&>]]></FIELD></TABLE></ELEMENT>')
        record = load_export(self.write(data))["tables"]["workflow_base"][0]
        self.assertEqual(record["values"]["workflowname"], "测试<&>")
        self.assertGreater(record["line"], 0)
        self.assertTrue(record["ref"])

    def test_empty_table_and_absent_table_distinguished(self):
        data = xml_document(table("workflow_base", "test") + '<ELEMENT ID="a" TABLENAME="WORKFLOWACTIONSET"/>')
        result = load_export(self.write(data))
        self.assertEqual(result["tables"]["workflowactionset"], [])
        self.assertNotIn("sapactionset", result["tables"])
        item = next(x for x in result["inventory"] if x["table"] == "workflowactionset")
        self.assertEqual(item["count"], 0)
        self.assertTrue(item["present"])

    def test_nonempty_base64_clob_and_encoding_assumption(self):
        value = base64.b64encode("中文说明".encode("gb18030")).decode()
        data = xml_document(table("workflow_flownode", value, field="showdesc", attrs='CLOBCOLUMN="showdesc，other"'))
        record = load_export(self.write(data))["tables"]["workflow_flownode"][0]
        self.assertEqual(record["values"]["showdesc"], "中文说明")
        self.assertEqual(record["decodings"]["showdesc"]["status"], "decoded")
        self.assertTrue(record["decodings"]["showdesc"]["assumption"])

    def test_explicit_encrypted_field_and_failed_decoding_is_not_empty(self):
        data = xml_document(table("workflow_base", "!!!bad-base64!!!", extra='FIELD_ENCRYPT="Y"'))
        result = load_export(self.write(data))
        record = result["tables"]["workflow_base"][0]
        self.assertEqual(record["values"]["name"], "!!!bad-base64!!!")
        self.assertEqual(record["decodings"]["name"]["status"], "failed")
        self.assertIn("FIELD_DECODE_FAILED", [x["code"] for x in result["issues"]])

    def test_uuid_logs_and_private_values_excluded_but_unknown_table_inventoried(self):
        data = xml_document(table("hrmresource", "private-password", field="password") +
                            table("workflow_newsetting", "new-config") +
                            '<ELEMENT ID="$LICENSE$"><TABLE ID="$LICENSE_Table$"><FIELD FIELDNAME="value" FIELDVALUE="LICENSE-SECRET"/></TABLE></ELEMENT>' +
                            '<ELEMENT ID="$UID_LOG$"><TABLE ID="$UID_LOG_Table$" TABLENAME="workflow_base"><FIELD FIELDNAME="$OLDUUID$" FIELDVALUE="old"/></TABLE></ELEMENT>')
        result = load_export(self.write(data))
        serialized = repr(result)
        self.assertNotIn("private-password", serialized)
        self.assertNotIn("LICENSE-SECRET", serialized)
        self.assertFalse(result["tables"].get("workflow_base"))
        item = next(x for x in result["inventory"] if x["table"] == "workflow_newsetting")
        self.assertFalse(item["supported"])

    def test_nested_tables_keep_parent_reference(self):
        data = xml_document('<ELEMENT ID="base" TABLENAME="workflow_base"><TABLE ID="base" TABLENAME="workflow_base"><FIELD FIELDNAME="id" FIELDVALUE="1"/><ELEMENT ID="child" TABLENAME="workflow_nodebase"><TABLE ID="child" TABLENAME="workflow_nodebase"><FIELD FIELDNAME="id" FIELDVALUE="2"/></TABLE></ELEMENT></TABLE></ELEMENT>')
        result = load_export(self.write(data))
        parent = result["tables"]["workflow_base"][0]
        child = result["tables"]["workflow_nodebase"][0]
        self.assertEqual(child["parent_ref"], parent["ref"])

    def test_nested_tables_with_distinct_names_have_distinct_inventory_counts(self):
        data = xml_document('<ELEMENT ID="labels" TABLENAME="HtmlLabelIndex"><TABLE TABLENAME="HtmlLabelIndex"><FIELD FIELDNAME="id" FIELDVALUE="1"/><TABLE TABLENAME="HTMLLABELINFO"><FIELD FIELDNAME="indexid" FIELDVALUE="1"/></TABLE></TABLE></ELEMENT>')
        result = load_export(self.write(data))
        counts = {item["table"]: item["count"] for item in result["inventory"]}
        self.assertEqual(counts, {"htmllabelindex": 1, "htmllabelinfo": 1})

    def test_zip_path_traversal_and_duplicate_entries_rejected(self):
        for entries in [[("../workflow.xml", xml_document(table("workflow_base", "x")))],
                        [("workflow.xml", b"x"), ("WORKFLOW.XML", b"y")]]:
            with self.subTest(entries=[x[0] for x in entries]):
                with self.assertRaises(ParseError):
                    load_export(self.zip(entries))

    def test_limits_precede_member_decompression(self):
        path = self.zip([("workflow.xml", xml_document(table("workflow_base", "x"))), ("large.txt", b"x" * 2000)])
        with self.assertRaises(ParseError) as ctx:
            load_export(path, limits=Limits(max_total_uncompressed=1000))
        self.assertEqual(ctx.exception.code, "ARCHIVE_LIMIT")

    def test_doctype_and_exml_rejected_explicitly(self):
        path = self.write(b'<!DOCTYPE root [<!ENTITY x SYSTEM "file:///C:/secret">]><root>&x;</root>')
        with self.assertRaises(ParseError) as ctx:
            load_export(path)
        self.assertEqual(ctx.exception.code, "UNSAFE_XML")
        with self.assertRaises(ParseError) as ctx:
            load_export(self.zip([("workflow.exml", b"encrypted")]))
        self.assertEqual(ctx.exception.code, "EXML_UNSUPPORTED")

    def test_malformed_and_non_workflow_xml_are_not_empty_success(self):
        for data in [b"<root>", b"<root><other/></root>"]:
            with self.assertRaises(ParseError):
                load_export(self.write(data))


if __name__ == "__main__":
    unittest.main()
