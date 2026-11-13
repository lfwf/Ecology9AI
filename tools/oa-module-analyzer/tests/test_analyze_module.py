import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo


SCRIPT = Path(__file__).resolve().parents[1] / "analyze_module.py"


def load_analyzer():
    assert SCRIPT.is_file(), "Offline module parser entry point has not been implemented"
    spec = importlib.util.spec_from_file_location("analyze_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def column(name, value=None, **attrs):
    from xml.sax.saxutils import quoteattr
    fields = {"name": name, **attrs}
    if value is not None:
        fields["value"] = value
    return "<column " + " ".join(f"{k}={quoteattr(v)}" for k, v in fields.items()) + "/>"


def record(**values):
    return "<data>" + "".join(column(k, v) for k, v in values.items()) + "</data>"


class ModuleAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def archive(self, members):
        path = self.base / "module.zip"
        with ZipFile(path, "w") as z:
            for name, content in members.items():
                info = ZipInfo(name)
                # Windows ZipInfo normalizes backslashes at construction; retain
                # an actually unsafe stored name to exercise the reader.
                info.filename = name
                info.orig_filename = name
                z.writestr(info, content)
        return path

    def analyze(self, members):
        api = load_analyzer()
        out = self.base / "result"
        summary = api.analyze_module(self.archive(members), out)
        return summary, {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in out.glob("*.json")}

    def test_preserves_complete_empty_absent_and_column_attributes(self):
        long_value = "完整\n" * 800
        xml = "<root datatype='mode' dataid='8'>\n<future_table>\n<data requestid='req'>\n" + column("text", long_value) + "\n" + column("empty", "") + "\n" + column("absent") + "\n" + column("ref", "91", requestid="external", cubeuuid="uuid") + "</data></future_table><empty_table/></root>"
        _, result = self.analyze({"data.xml": xml})
        module = result["module"]
        row = next(iter(module["records"].values()))
        self.assertEqual(row["values"]["text"], long_value)
        self.assertEqual(row["values"]["empty"], "")
        self.assertIsNone(row["values"]["absent"])
        self.assertEqual(row["column_metadata"]["ref"]["attributes"]["cubeuuid"], "uuid")
        self.assertEqual(row["attributes"]["requestid"], "req")
        evidence = result["evidence"]["items"][row["column_metadata"]["empty"]["evidence"]]
        self.assertEqual((evidence["member"], evidence["line"]), ("data.xml", 5))
        self.assertIn("column", evidence["xpath"])
        inventory = result["table-inventory"]["tables"]
        self.assertEqual(next(t for t in inventory if t["table"] == "empty_table")["state"], "empty_section")

    def test_keeps_export_values_external_references_overrides_and_config_separate(self):
        _, result = self.analyze({
            "data.xml": "<root><modeinfo>" + record(id="8", modename="模块") + "</modeinfo></root>",
            "froeignData.xml": "<root><modeinfo><data id='8' uuid='outside'/></modeinfo></root>",
            "modifyInfo.xml": "<root><modeinfo>" + record(id="8", modename="覆盖模块") + "</modeinfo></root>",
            "config/config.xml": "<root cversion='9'><modeinfo/></root>",
            "dataForm.xml": "<root><uf_example requestid='form'/></root>",
        })
        inventory = result["table-inventory"]["tables"]
        states = {t["member"]: t["state"] for t in inventory}
        self.assertEqual(states["data.xml"], "full_values")
        self.assertEqual(states["froeignData.xml"], "external_reference")
        self.assertEqual(states["modifyInfo.xml"], "override_values")
        self.assertEqual(states["config/config.xml"], "configuration_marker")
        self.assertEqual(states["dataForm.xml"], "empty_business_data")
        self.assertEqual(result["module"]["normalized"]["identity"]["name"], "模块")
        refs = result["module"]["normalized"]["external_references"]
        self.assertEqual(refs[0]["attributes"]["uuid"], "outside")

    def test_maps_chinese_labels_options_and_form_layout_base64_json(self):
        xml = "<root dataid='8' datatype='mode'>"
        xml += "<modeinfo>" + record(id="8", formid="-9", modename="考勤") + "</modeinfo>"
        xml += "<workflow_bill>" + record(id="-9", tablename="uf_test") + "</workflow_bill>"
        xml += "<htmllabelinfo><data>" + column("indexid", "-10") + column("languageid", "7") + column("labelname", b64("人员类别"), isencrypt="true") + "</data></htmllabelinfo>"
        xml += "<workflow_billfield>" + record(id="11", fieldname="rylb", fieldlabel="-10", fieldhtmltype="5", fielddbtype="int") + "</workflow_billfield>"
        xml += "<workflow_selectitem>" + record(id="30", fieldid="11", selectvalue="0", selectname="正式员工", cancel="0", isdefault="y") + "</workflow_selectitem>"
        xml += "<modehtmllayout><data>" + column("id", "12") + column("type", "1") + column("datajson", b64('{"eformdesign":{"eattr":{"formname":"新建"}}}'), isencrypt="true") + "</data></modehtmllayout></root>"
        _, result = self.analyze({"data.xml": xml, "config/config.xml": "<root datatype='mode' cversion='9.00.2404.02'/>"})
        norm = result["module"]["normalized"]
        self.assertEqual(norm["identity"]["table"], "uf_test")
        self.assertEqual(norm["fields"][0]["label"], "人员类别")
        self.assertEqual(norm["fields"][0]["options"][0]["name"], "正式员工")
        self.assertEqual(norm["layouts"][0]["type_name"], "新建")
        row = result["module"]["records"][norm["layouts"][0]["record"]]
        self.assertEqual(row["decoded"]["datajson"]["value"]["eformdesign"]["eattr"]["formname"], "新建")
        self.assertEqual(row["decoded"]["datajson"]["encoding"], "base64-utf8")
        self.assertEqual(row["decoded"]["datajson"]["source_evidence"], row["column_metadata"]["datajson"]["evidence"])

    def test_unmarked_base64_shaped_ascii_name_is_ambiguous_and_never_applied(self):
        api = load_analyzer()
        for raw, candidate in [("5Lit5paH", "中文"), ("TWFu", "Man")]:
            with self.subTest(raw=raw):
                result = api.decode_value(raw, "selectname", {}, "e000001")
                self.assertEqual(result["status"], "ambiguous")
                self.assertEqual(result["value"], raw)
                self.assertIsNone(result["encoding"])
                self.assertEqual(result["candidate"]["value"], candidate)
                self.assertEqual(result["candidate"]["encoding"], "base64-utf8")
                self.assertEqual(result["interpretation_source"]["kind"], "shape_only")
                marked = api.decode_value(raw, "selectname", {"isencrypt": "true"}, "e000002")
                self.assertEqual(marked["status"], "decoded")
                self.assertEqual(marked["value"], candidate)
                self.assertEqual(marked["interpretation_source"]["kind"], "column_attribute")
                self.assertEqual(marked["interpretation_source"]["evidence"], "e000002")

    def test_unknown_profile_does_not_normalize_labels_or_options_from_candidates(self):
        raw = "5Lit5paH"
        xml = "<root datatype='mode'><htmllabelinfo>" + record(indexid="-1", languageid="7", labelname=raw) + "</htmllabelinfo><workflow_billfield>" + record(id="1", fieldname="name", fieldlabel="-1") + "</workflow_billfield><workflow_selectitem>" + record(fieldid="1", selectvalue="0", selectname=raw) + "</workflow_selectitem></root>"
        _, result = self.analyze({"data.xml": xml, "config/config.xml": "<root cversion='future-version'/>"})
        norm = result["module"]["normalized"]
        self.assertEqual(norm["fields"][0]["label"], raw)
        self.assertEqual(norm["select_options"][0]["name"], raw)
        self.assertTrue(any(warning["code"] == "ambiguous_encoding" for warning in result["module"]["warnings"]))
        for row in result["module"]["records"].values():
            for decoded in row["decoded"].values():
                self.assertEqual(decoded["status"], "ambiguous")
                self.assertEqual(decoded["candidate"]["value"], "中文")

    def test_layout_types_are_candidates_when_export_version_or_datatype_is_unknown(self):
        for datatype, version in [("mode", None), ("mode", "future-version"), ("workflow", "9.00.2404.02")]:
            with self.subTest(datatype=datatype, version=version):
                members = {"data.xml": f"<root datatype='{datatype}'><modehtmllayout>" + record(id="1", type="0") + record(id="2", type="1") + record(id="3", type="2") + "</modehtmllayout></root>"}
                if version is not None:
                    members["config/config.xml"] = f"<root cversion='{version}'/>"
                _, result = self.analyze(members)
                layouts = result["module"]["normalized"]["layouts"]
                self.assertEqual([item["type"] for item in layouts], ["0", "1", "2"])
                self.assertEqual([item["type_name"] for item in layouts], ["未知"] * 3)
                self.assertEqual([item["type_name_candidate"] for item in layouts], ["显示", "新建", "编辑"])
                for item in layouts:
                    self.assertEqual(item["type_interpretation"]["status"], "candidate")
                    source = item["type_interpretation"]["sources"][0]
                    self.assertEqual(source["path"], "formmode/setup/ModeShareAdd.jsp")
                    self.assertEqual(source["sha256"], "c38623617df343564b83ef5a2c684832d2c43248bde9c6903b84624e9ebcab4e")

    def test_verified_layout_profile_is_order_independent_and_has_metadata_evidence(self):
        _, result = self.analyze({
            "data.xml": "<root datatype='mode'><modehtmllayout>" + record(id="1", type="1") + "</modehtmllayout></root>",
            "config/config.xml": "<root datatype='mode' cversion='9.00.2404.02'/>"
        })
        layout = result["module"]["normalized"]["layouts"][0]
        self.assertEqual(layout["type_name"], "新建")
        self.assertEqual(layout["type_interpretation"]["status"], "applied")
        self.assertEqual(layout["type_interpretation"]["matched_metadata"], {"datatype": "mode", "cversion": "9.00.2404.02"})
        self.assertTrue(layout["type_interpretation"]["metadata_evidence"])
        for evidence_id in layout["type_interpretation"]["metadata_evidence"]:
            self.assertIn(evidence_id, result["evidence"]["items"])

    def test_conflicting_export_version_does_not_apply_layout_profile(self):
        _, result = self.analyze({
            "data.xml": "<root datatype='mode' cversion='future-version'><modehtmllayout>" + record(id="1", type="1") + "</modehtmllayout></root>",
            "config/config.xml": "<root datatype='mode' cversion='9.00.2404.02'/>"
        })
        layout = result["module"]["normalized"]["layouts"][0]
        self.assertEqual(layout["type_name"], "未知")
        self.assertEqual(layout["type_interpretation"]["status"], "candidate")

    def test_unknown_sections_browser_sql_and_duplicate_columns_remain_reviewable(self):
        _, result = self.analyze({
            "data.xml": "<root><future_table><data>" + column("x", "1") + column("x", "2") + "<future nested='true'>原样</future></data></future_table><future_node a='b'>文本<inner>子</inner>尾</future_node></root>",
            "browser.xml": "<root><browser name='demo'><set property='search' value='select 1'/><set property='empty' value=''/></browser></root>",
            "file/note.txt": b"not executed",
        })
        module = result["module"]
        row = next(r for r in module["records"].values() if r["table"] == "future_table")
        self.assertEqual(row["values"]["x"], "1")
        self.assertEqual(row["duplicate_columns"][0]["value"], "2")
        self.assertEqual(row["extensions"][0]["text"], "原样")
        doc = next(d for d in module["documents"] if d["member"] == "data.xml")
        self.assertEqual(doc["sections"][1]["raw"]["children"][0]["tail"], "尾")
        browser = next(r for r in module["records"].values() if r["table"] == "browser")
        self.assertEqual(browser["values"]["search"], "select 1")
        self.assertEqual(browser["values"]["empty"], "")
        self.assertEqual(next(m for m in result["manifest"]["members"] if m["name"] == "file/note.txt")["status"], "hashed_only")

    def test_reports_all_domain_tables_in_categories_without_runtime_claims(self):
        tables = {"modeinfo": "module", "workflow_billfield": "fields", "mode_customsearch": "lists", "modehtmllayout": "forms", "moderightinfo": "permissions", "mode_pageexpand": "buttons", "modeattrlinkage": "linkages", "mode_timedtask": "scheduled_tasks"}
        _, result = self.analyze({"data.xml": "<root>" + "".join(f"<{table}>" + record(id="1") + f"</{table}>" for table in tables) + "</root>"})
        categories = result["module"]["normalized"]["categories"]
        for table, category in tables.items():
            self.assertTrue(any(result["module"]["records"][rid]["table"] == table for rid in categories[category]), table)
        self.assertIn("offline_export_only", result["module"]["limitations"])

    def test_script_decode_has_source_hash_and_unknown_encoding_is_explicit(self):
        script = 'WfForm.changeFieldValue("field1", {value:"0"});'
        xml = "<root><modehtmllayout><data>" + column("scripts", b64(script), isencrypt="true") + column("scriptstr", "enc:unknown", isencrypt="true") + "</data></modehtmllayout></root>"
        _, result = self.analyze({"data.xml": xml})
        scripts = result["module"]["normalized"]["scripts"]
        self.assertEqual(scripts[0]["status"], "decoded")
        row = result["module"]["records"][scripts[0]["record"]]
        self.assertEqual(row["decoded"]["scripts"]["value"], script)
        self.assertEqual(len(scripts[0]["input_sha256"]), 64)
        self.assertEqual(scripts[1]["status"], "unsupported")

    def test_rejects_traversal_duplicate_casefold_symlink_and_limits(self):
        api = load_analyzer()
        for name in ["../data.xml", "/data.xml", "C:/data.xml", "a\\data.xml"]:
            with self.subTest(name=name):
                with self.assertRaises(api.ModuleParseError):
                    api.analyze_module(self.archive({name: "<root/>"}), self.base / "bad")
        path = self.base / "duplicate.zip"
        with ZipFile(path, "w") as z:
            z.writestr("data.xml", "<root/>")
            z.writestr("DATA.XML", "<root/>")
        with self.assertRaises(api.ModuleParseError):
            api.analyze_module(path, self.base / "duplicate")
        info = ZipInfo("link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        with ZipFile(path, "w") as z:
            z.writestr(info, "target")
        with self.assertRaises(api.ModuleParseError):
            api.analyze_module(path, self.base / "link")
        with self.assertRaises(api.ModuleParseError):
            api.analyze_module(self.archive({"data.xml": "<root/>"}), self.base / "limit", limits={"max_member_bytes": 2})

    def test_rejects_dtd_entities_malformed_xml_and_corrupt_zip(self):
        api = load_analyzer()
        for xml in ["<!DOCTYPE root [<!ENTITY secret SYSTEM 'file:///private'>]><root>&secret;</root>", "<root><broken></root>"]:
            with self.subTest(xml=xml):
                with self.assertRaises(api.ModuleParseError):
                    api.analyze_module(self.archive({"data.xml": xml}), self.base / "badxml")
        broken = self.base / "broken.zip"
        broken.write_bytes(b"not a zip")
        with self.assertRaises(api.ModuleParseError):
            api.analyze_module(broken, self.base / "broken")

    def test_manifest_hashes_outputs_and_cli_prints_small_json_summary(self):
        import hashlib
        path = self.archive({"data.xml": "<root dataid='8'><modeinfo>" + record(id="8", modename="示例") + "</modeinfo></root>"})
        out = self.base / "cli"
        process = subprocess.run([sys.executable, str(SCRIPT), str(path), "--output", str(out)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        summary = json.loads(process.stdout)
        self.assertEqual(summary["status"], "ok")
        self.assertLess(len(process.stdout), 2000)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        module = json.loads((out / "module.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["analyzer_version"], "0.1.0")
        self.assertEqual(module["analyzer_version"], manifest["analyzer_version"])
        self.assertFalse(manifest["runtime_verified"])
        self.assertFalse(module["runtime_verified"])
        self.assertEqual(manifest["input"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        for name, expected in manifest["outputs"].items():
            self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), expected)
        self.assertEqual(set(manifest["outputs"]), {"module.json", "evidence.json", "table-inventory.json"})
        self.assertEqual(path.read_bytes(), (self.base / "module.zip").read_bytes())

    def test_input_cannot_be_overwritten_through_hardlinked_output(self):
        import os
        api = load_analyzer()
        path = self.archive({"data.xml": "<root/>"})
        out = self.base / "hardlink"
        out.mkdir()
        before = path.read_bytes()
        os.link(path, out / "module.json")
        with self.assertRaises(api.ModuleParseError):
            api.analyze_module(path, out)
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_nonfinite_or_duplicate_key_json_stays_text_with_explicit_error(self):
        for text in ['{"value":NaN}', '{"value":1e999}', '{"value":1,"value":2}', '{"value":"\\ud800"}']:
            with self.subTest(text=text):
                _, result = self.analyze({"data.xml": "<root><modehtmllayout><data>" + column("datajson", b64(text), isencrypt="true") + "</data></modehtmllayout></root>"})
                row = next(iter(result["module"]["records"].values()))
                self.assertEqual(row["decoded"]["datajson"]["value"], text)
                self.assertEqual(row["decoded"]["datajson"]["format"], "text")
                self.assertTrue(row["decoded"]["datajson"]["json_error"])

    def test_preserves_nonwhitespace_mixed_content_and_qualified_unknown_names(self):
        _, result = self.analyze({"data.xml": "<root xmlns:x='urn:future'>前文<x:future/>后文<table><data>行文" + column("v", "1") + "列后</data>行后</table></root>"})
        doc = result["module"]["documents"][0]
        self.assertEqual(doc["text"], "前文")
        self.assertEqual(doc["sections"][0]["tail"], "后文")
        self.assertEqual(doc["sections"][0]["qualified_name"], "{urn:future}future")
        row = next(iter(result["module"]["records"].values()))
        self.assertEqual(row["tail"], "行后")
        self.assertEqual(row["column_metadata"]["v"]["tail"], "列后")

    def test_checks_all_archive_limits_exact_duplicates_and_utf16_entities(self):
        import zipfile
        api = load_analyzer()
        for limits in [{"max_members": 1}, {"max_total_bytes": 10}, {"max_archive_bytes": 10}, {"max_xml_elements": 1}]:
            with self.subTest(limits=limits):
                path = self.archive({"data.xml": "<root><table/></root>", "note.txt": "123"})
                with self.assertRaises(api.ModuleParseError):
                    api.analyze_module(path, self.base / "limits", limits=limits)
        path = self.base / "compressed.zip"
        with ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("data.xml", "<root>" + "0" * 100000 + "</root>")
        with self.assertRaises(api.ModuleParseError):
            api.analyze_module(path, self.base / "ratio", limits={"max_compression_ratio": 2})
        with ZipFile(path, "w") as z:
            with self.assertWarns(UserWarning):
                z.writestr("data.xml", "<root/>")
                z.writestr("data.xml", "<root/>")
        with self.assertRaises(api.ModuleParseError):
            api.analyze_module(path, self.base / "same-name")
        xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE root [<!ENTITY x "text">]><root>&x;</root>'
        with self.assertRaises(api.ModuleParseError):
            api.analyze_module(self.archive({"data.xml": xml.encode("utf-16")}), self.base / "utf16")

    def test_optional_edesign_cipher_is_decoded_and_invalid_cipher_is_unsupported(self):
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except ImportError:
            self.skipTest("optional cryptography package is not installed")
        script = 'WfForm.changeFieldValue("field9", {value:"1"});'
        payload = script.encode("utf-8")
        padding = 16 - len(payload) % 16
        encoder = Cipher(algorithms.AES(b"WEAVER E-DESIGN."), modes.CBC(b"weaver e-design.")).encryptor()
        encoded = (encoder.update(payload + bytes([padding]) * padding) + encoder.finalize()).hex()
        _, result = self.analyze({"data.xml": "<root><modehtmllayout><data>" + column("scripts", encoded, isencrypt="true") + column("scriptstr", "0" * 32, isencrypt="true") + "</data></modehtmllayout></root>"})
        row = next(iter(result["module"]["records"].values()))
        self.assertEqual(row["decoded"]["scripts"]["value"], script)
        self.assertEqual(row["decoded"]["scripts"]["profile"], "weaver-e9-edesign-aes-cbc-v1")
        self.assertEqual(row["decoded"]["scriptstr"]["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
