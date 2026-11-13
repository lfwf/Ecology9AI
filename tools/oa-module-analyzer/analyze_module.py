#!/usr/bin/env python3
"""Read a Weaver form-model module ZIP without importing or executing it.

Only archive bytes and XML are read. Values stay strings (an absent value
attribute is None); exported, override, foreign-reference and marker files stay
separate. The module JSON holds raw values once, with normalized references and
an independent evidence index. This file has no dependency on the author's OA
installation or another analyzer.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import unicodedata
from zipfile import BadZipFile, LargeZipFile, ZipFile

from lxml import etree


SCHEMA_VERSION = "1.0"
TOOL_VERSION = "0.1.0"
DEFAULT_LIMITS = {
    "max_archive_bytes": 128 * 1024 * 1024,
    "max_members": 2000,
    "max_member_bytes": 32 * 1024 * 1024,
    "max_total_bytes": 256 * 1024 * 1024,
    "max_compression_ratio": 1000,
    "max_xml_elements": 300000,
}
SCRIPT_COLUMNS = {"scripts", "scriptstr", "jscode", "javascript", "script", "jscontent"}
JSON_COLUMNS = {"datajson", "pluginjson", "littlecardjson"}
LABEL_COLUMNS = {"labelname", "indexdesc", "selectname", "expenddesc"}
CATEGORY_NAMES = ("module", "fields", "lists", "forms", "permissions", "buttons", "linkages", "scheduled_tasks", "browsers", "workflows", "select_options", "labels", "other")
LAYOUT_TYPE_CANDIDATES = {"1": "新建", "0": "显示", "2": "编辑"}
LAYOUT_TYPE_PROFILE = "weaver-mode-9.00.2404.02-local-verified"
# These are provenance for a checked local source snapshot, not runtime files
# to import and not an assertion that every Weaver version uses these codes.
LAYOUT_TYPE_SOURCES = [
    {"path": "formmode/setup/ModeShareAdd.jsp", "lines": [[1724, 1735], [1742, 1742]],
     "sha256": "c38623617df343564b83ef5a2c684832d2c43248bde9c6903b84624e9ebcab4e"},
    {"path": "formmode/setup/FormModeHtmlBrowserIframe.jsp", "lines": [[94, 103]],
     "sha256": "23ed548339fc1b5a5b71c44e7313aa68d75a3632d4a2b4c311663b23fbdcc618"},
]


class ModuleParseError(ValueError):
    """Untrusted or unsupported archive structure; no business action was taken."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tag_name(element) -> str:
    if not isinstance(element.tag, str):
        return "#comment" if element.tag is etree.Comment else "#processing-instruction"
    return etree.QName(element).localname


def source_role(member: str) -> str:
    name = PurePosixPath(member).name.casefold()
    return {
        "data.xml": "export_values",
        "froeigndata.xml": "external_references",
        "foreigndata.xml": "external_references",
        "modifyinfo.xml": "overrides",
        "dataform.xml": "business_data",
        "datasetform.xml": "business_data",
        "browser.xml": "browsers",
        "workflowset.xml": "workflow_settings",
        "file.xml": "file_index",
    }.get(name, "configuration" if member.casefold().endswith("config/config.xml") else "unknown_xml")


def category(table: str) -> str:
    name = table.casefold()
    if name in {"modeinfo", "workflow_bill", "workflow_billdetailtable"}:
        return "module"
    if name.startswith("htmllabel"):
        return "labels"
    if "selectitem" in name:
        return "select_options"
    if "timedtask" in name or "remindjob" in name:
        return "scheduled_tasks"
    if any(term in name for term in ("right", "authoriz", "shareinfo")):
        return "permissions"
    if any(term in name for term in ("linkage", "expressions", "expressionbase", "fieldexp", "field_assign", "relatefield", "defaultvalue", "showchange")):
        return "linkages"
    if any(term in name for term in ("button", "pageexpand", "toolbar")):
        return "buttons"
    if "browser" in name or name == "browser":
        return "browsers"
    if "workflow" in name and name != "workflow_billfield":
        return "workflows"
    if name in {"workflow_billfield", "modefieldattr", "modefieldtype"}:
        return "fields"
    if any(term in name for term in ("layout", "modeform", "jscode")):
        return "forms"
    if any(term in name for term in ("customsearch", "customdspfield", "quicksearch", "batchset", "searchrow", "searchpage", "report", "customcount", "searchline")):
        return "lists"
    return "other"


def _validate_members(archive: ZipFile, limits: dict) -> list:
    infos = archive.infolist()
    if len(infos) > limits["max_members"]:
        raise ModuleParseError("ZIP member count exceeds configured limit")
    seen, total = set(), 0
    for info in infos:
        name = info.filename
        if getattr(info, "orig_filename", name) != name:
            raise ModuleParseError(f"ZIP member path was normalized or truncated by the reader: {info.orig_filename!r}")
        path = PurePosixPath(name)
        if (not name or "\\" in name or "\x00" in name or ":" in name
                or path.is_absolute() or any(part in {".", ".."} for part in name.rstrip("/").split("/"))
                or any(not part for part in name.rstrip("/").split("/"))):
            raise ModuleParseError(f"Unsafe ZIP member path: {name!r}")
        key = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
        if key in seen:
            raise ModuleParseError(f"Duplicate or case-colliding ZIP member: {name!r}")
        seen.add(key)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
            raise ModuleParseError(f"ZIP links and special members are unsupported: {name!r}")
        if info.flag_bits & 1:
            raise ModuleParseError(f"Encrypted ZIP member is unsupported: {name!r}")
        if info.file_size > limits["max_member_bytes"]:
            raise ModuleParseError(f"ZIP member exceeds configured byte limit: {name!r}")
        total += info.file_size
        if total > limits["max_total_bytes"]:
            raise ModuleParseError("ZIP total uncompressed bytes exceed configured limit")
        if info.file_size > max(1, info.compress_size) * limits["max_compression_ratio"]:
            raise ModuleParseError(f"ZIP compression ratio exceeds configured limit: {name!r}")
    return infos


def _safe_xml(data: bytes, member: str, limits: dict):
    # XMLParser disables network, DTD loading and entity expansion. Rejecting the
    # declaration as well catches internal entities, including UTF-16 documents.
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", data.replace(b"\x00", b""), re.I):
        raise ModuleParseError(f"DTD/entity declarations are forbidden: {member}")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True,
                             huge_tree=False, recover=False, remove_comments=False,
                             remove_pis=False, strip_cdata=False)
    try:
        root = etree.fromstring(data, parser)
    except (etree.XMLSyntaxError, ValueError) as error:
        raise ModuleParseError(f"Invalid XML in {member}: {error}") from error
    if root.getroottree().docinfo.doctype:
        raise ModuleParseError(f"DTD declarations are forbidden: {member}")
    if sum(1 for _ in root.iter()) > limits["max_xml_elements"]:
        raise ModuleParseError(f"XML element count exceeds configured limit: {member}")
    return root


def _printable(text: str) -> bool:
    return not any(unicodedata.category(char) == "Cc" and char not in "\r\n\t" for char in text)


def _strict_json(text: str):
    def constant(value):
        raise ValueError(f"Nonstandard JSON constant: {value}")

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"Nonfinite JSON number: {value}")
        return parsed

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON object key: {key!r}")
            result[key] = value
        return result

    parsed = json.loads(text, parse_constant=constant, parse_float=number, object_pairs_hook=pairs)
    pending = [parsed]
    while pending:
        value = pending.pop()
        if isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("Unpaired Unicode surrogate in JSON text")
        if isinstance(value, dict):
            pending.extend(value)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return parsed


def decode_value(value: str | None, name: str, attributes: dict, evidence: str) -> dict | None:
    """Decode marked columns; unmarked Base64-shaped text remains a candidate.

    In module ZIP exports isencrypt=true commonly denotes Base64 transport
    encoding. It does not by itself prove encryption. Unknown data is retained.
    The optional AES branch only recognizes the established E-Design profile.
    """
    marked = attributes.get("isencrypt", "").lower() == "true"
    is_script = name.casefold() in SCRIPT_COLUMNS
    candidate = marked or name.casefold() in LABEL_COLUMNS | JSON_COLUMNS | SCRIPT_COLUMNS
    if not candidate or value is None:
        return None
    result = {"status": "unsupported", "encoding": None,
              "source_evidence": evidence, "input_sha256": sha256(value.encode("utf-8"))}
    if value == "":
        return {**result, "status": "empty", "encoding": "empty", "value": "",
                "decoded_sha256": sha256(b"")}
    text, encoding, raw = None, None, None
    compact = re.sub(r"\s+", "", value)
    try:
        decoded = base64.b64decode(compact, validate=True)
        possible = decoded.decode("utf-8")
        # Readable UTF-8 is only a candidate: an ASCII business name can itself
        # be valid Base64. Shape alone never authorizes changing its meaning.
        if _printable(possible) and (marked or possible):
            if not marked:
                return {**result, "status": "ambiguous", "value": value,
                        "candidate": {"value": possible, "encoding": "base64-utf8", "decoded_sha256": sha256(decoded)},
                        "interpretation_source": {"kind": "shape_only", "evidence": evidence},
                        "reason": "No explicit encoding marker; candidate is not applied"}
            text, encoding, raw = possible, "base64-utf8", decoded
            result["interpretation_source"] = {"kind": "column_attribute", "attribute": "isencrypt",
                                                "value": "true", "evidence": evidence}
    except (ValueError, binascii.Error, UnicodeDecodeError):
        pass
    if text is None and is_script and re.fullmatch(r"[0-9a-fA-F]+", compact) and len(compact) % 32 == 0:
        result["profile"] = "weaver-e9-edesign-aes-cbc-v1"
        result["interpretation_source"] = {"kind": "decoder_profile", "profile": result["profile"], "evidence": evidence}
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            cipher = bytes.fromhex(compact)
            decryptor = Cipher(algorithms.AES(b"WEAVER E-DESIGN."), modes.CBC(b"weaver e-design.")).decryptor()
            decoded = decryptor.update(cipher) + decryptor.finalize()
            padding = decoded[-1]
            if not 1 <= padding <= 16 or decoded[-padding:] != bytes([padding]) * padding:
                raise ValueError("Invalid E-Design PKCS7 padding")
            raw = decoded[:-padding]
            for charset in ("utf-8", "gb18030"):
                try:
                    text = raw.decode(charset)
                    encoding = "edesign-aes-cbc-" + charset
                    break
                except UnicodeDecodeError:
                    pass
            if text is None or not _printable(text):
                raise ValueError("Decoded E-Design text is unsupported")
        except (ImportError, ValueError) as error:
            result["reason"] = str(error)
            return result
    if text is None and not marked:
        if is_script and (re.match(r"(?i)^\s*(?:enc(?:rypted)?|base64|aes|edesign)\s*:", value) or re.fullmatch(r"[A-Za-z0-9+/=_-]{24,}", value.strip())):
            result["reason"] = "Unrecognized opaque script encoding"
            return result
        text, encoding, raw = value, "plain-utf8", value.encode("utf-8")
    if text is None:
        result["reason"] = "Marked export value is not supported Base64 UTF-8 text"
        return result
    result.update(status="plain" if encoding == "plain-utf8" else "decoded",
                  encoding=encoding, decoded_sha256=sha256(raw), value=text)
    if name.casefold() in JSON_COLUMNS:
        try:
            result["value"] = _strict_json(text)
            result["format"] = "json"
        except (ValueError, RecursionError) as error:
            result["format"] = "text"
            result["json_error"] = str(error)
    elif is_script:
        result["format"] = "script_text"
        result["line_count"] = text.count("\n") + 1
    return result


class _Reader:
    def __init__(self):
        self.evidence = {}
        self.records = {}
        self.inventory = []
        self.documents = []
        self.warnings = []

    def location(self, node, member: str, kind: str) -> str:
        evidence_id = f"e{len(self.evidence) + 1:06d}"
        self.evidence[evidence_id] = {"member": member, "line": node.sourceline,
                                      "xpath": node.getroottree().getpath(node), "kind": kind}
        return evidence_id

    def raw_node(self, node, member: str) -> dict:
        result = {"tag": node.tag if isinstance(node.tag, str) else tag_name(node),
                  "attributes": dict(node.attrib), "text": node.text,
                  "tail": node.tail, "evidence": self.location(node, member, "raw_node")}
        if len(node):
            result["children"] = [self.raw_node(child, member) for child in node]
        return result

    def row(self, node, table: str, role: str, member: str, property_mode=False) -> str:
        rid = f"r{len(self.records) + 1:05d}"
        row = {"table": table, "source_role": role, "attributes": dict(node.attrib),
               "evidence": self.location(node, member, "record"), "values": {},
               "column_metadata": {}, "decoded": {}}
        extensions, duplicates = [], []
        for child in node:
            column_tag = "set" if property_mode else "column"
            key = child.get("property" if property_mode else "name")
            if tag_name(child) != column_tag or key is None:
                extensions.append(self.raw_node(child, member))
                continue
            value = child.get("value")
            attrs = {k: v for k, v in child.attrib.items() if k not in {"name" if not property_mode else "property", "value"}}
            evidence = self.location(child, member, "column")
            metadata = {"attributes": attrs, "evidence": evidence}
            if child.text is not None:
                metadata["text"] = child.text
            if child.tail and child.tail.strip():
                metadata["tail"] = child.tail
            if isinstance(child.tag, str) and child.tag.startswith("{"):
                metadata["qualified_name"] = child.tag
            if len(child):
                metadata["children"] = [self.raw_node(item, member) for item in child]
            if key in row["values"]:
                duplicates.append({"name": key, "value": value, **metadata})
                self.warnings.append({"code": "duplicate_column", "record": rid, "column": key, "evidence": evidence})
                continue
            row["values"][key] = value
            row["column_metadata"][key] = metadata
            decoded = decode_value(value, key, attrs, evidence)
            if decoded is not None:
                row["decoded"][key] = decoded
                if decoded["status"] == "unsupported":
                    self.warnings.append({"code": "unsupported_encoding", "record": rid, "column": key, "evidence": evidence})
                elif decoded["status"] == "ambiguous":
                    self.warnings.append({"code": "ambiguous_encoding", "record": rid, "column": key, "evidence": evidence})
                elif "json_error" in decoded:
                    self.warnings.append({"code": "decoded_json_invalid", "record": rid, "column": key, "evidence": evidence})
        if extensions:
            row["extensions"] = extensions
        if duplicates:
            row["duplicate_columns"] = duplicates
        if node.text and node.text.strip():
            row["text"] = node.text
        if node.tail and node.tail.strip():
            row["tail"] = node.tail
        self.records[rid] = row
        return rid

    def document(self, root, member: str):
        role = source_role(member)
        doc = {"member": member, "role": role, "root_tag": root.tag,
               "root_attributes": dict(root.attrib), "evidence": self.location(root, member, "document"),
               "sections": []}
        if root.nsmap:
            doc["namespaces"] = {key or "": value for key, value in root.nsmap.items()}
        if root.text and root.text.strip():
            doc["text"] = root.text
        for node in root:
            name = tag_name(node)
            section = {"name": name, "attributes": dict(node.attrib),
                       "evidence": self.location(node, member, "section"), "records": []}
            if isinstance(node.tag, str) and node.tag.startswith("{"):
                section["qualified_name"] = node.tag
            if node.tail and node.tail.strip():
                section["tail"] = node.tail
            rows = [child for child in node if tag_name(child) == "data"]
            if role == "browsers" and name == "browser":
                section["records"].append(self.row(node, name, role, member, property_mode=True))
            else:
                for row in rows:
                    section["records"].append(self.row(row, name, role, member))
                extra = [child for child in node if tag_name(child) != "data"]
                if extra or (node.text and node.text.strip()):
                    # A wholly unknown section is one complete generic tree.
                    if not rows:
                        section["raw"] = self.raw_node(node, member)
                    else:
                        section["extensions"] = [self.raw_node(child, member) for child in extra]
                        if node.text and node.text.strip():
                            section["text"] = node.text
            count = len(section["records"])
            value_count = sum(len(self.records[rid]["values"]) for rid in section["records"])
            if role == "external_references":
                state = "external_reference" if count else "empty_section"
            elif role == "overrides":
                state = "override_values" if count else "empty_section"
            elif role == "configuration":
                state = "configuration_values" if count else "configuration_marker"
            elif role == "business_data":
                state = "business_data" if count else "empty_business_data"
            elif count:
                state = "full_values" if value_count else "attribute_records"
            elif "raw" in section:
                state = "uninterpreted_section"
            else:
                state = "empty_section"
            section["state"] = state
            self.inventory.append({"member": member, "table": name, "role": role,
                                   "state": state, "record_count": count,
                                   "column_count": value_count, "category": category(name),
                                   "evidence": section["evidence"]})
            doc["sections"].append(section)
        self.documents.append(doc)

    def normalized(self) -> dict:
        norm = {"identity": {}, "fields": [], "labels": {}, "select_options": [],
                "layouts": [], "scripts": [], "categories": {name: [] for name in CATEGORY_NAMES},
                "external_references": [], "override_records": []}
        by_table = {}
        for rid, row in self.records.items():
            role, table = row["source_role"], row["table"].casefold()
            if role == "external_references":
                norm["external_references"].append({"table": row["table"], "attributes": row["attributes"], "record": rid, "evidence": row["evidence"]})
                continue
            if role == "overrides":
                norm["override_records"].append(rid)
                continue
            if role not in {"export_values", "browsers", "workflow_settings"}:
                continue
            by_table.setdefault(table, []).append((rid, row))
            norm["categories"][category(table)].append(rid)

        def text(row, key, default=""):
            decoded = row["decoded"].get(key, {})
            value = (decoded.get("value", row["values"].get(key, default))
                     if decoded.get("status") in {"decoded", "plain", "empty"}
                     else row["values"].get(key, default))
            return value if isinstance(value, str) else default

        labels = norm["labels"]
        for table in ("htmllabelinfo", "htmllabelindex"):
            for rid, row in by_table.get(table, []):
                values = row["values"]
                label_id = values.get("indexid" if table == "htmllabelinfo" else "id")
                key = "labelname" if table == "htmllabelinfo" else "indexdesc"
                if label_id is None:
                    continue
                label = {"name": text(row, key), "language": values.get("languageid"), "record": rid,
                         "evidence": row["column_metadata"].get(key, {}).get("evidence", row["evidence"])}
                labels.setdefault(label_id, []).append(label)

        def label_name(label_id):
            candidates = labels.get(label_id, [])
            preferred = next((item for item in candidates if item["language"] == "7"), candidates[0] if candidates else {})
            return preferred.get("name")

        metadata = {}
        for doc in self.documents:
            if doc["role"] in {"export_values", "configuration"}:
                metadata.update({k: v for k, v in doc["root_attributes"].items() if k in {"dataid", "datatype", "dbtype", "defaultcharset", "cversion"}})
        norm["identity"].update(metadata)
        module_rows = by_table.get("modeinfo", [])
        selected = next((item for item in module_rows if item[1]["values"].get("id") == metadata.get("dataid")), module_rows[0] if module_rows else None)
        if selected:
            rid, row = selected
            norm["identity"].update(id=row["values"].get("id"), name=text(row, "modename"),
                                    form_id=row["values"].get("formid"), record=rid, evidence=row["evidence"])
        form_rows = by_table.get("workflow_bill", [])
        selected_form = next((item for item in form_rows if item[1]["values"].get("id") == norm["identity"].get("form_id")), form_rows[0] if len(form_rows) == 1 else None)
        if selected_form:
            rid, row = selected_form
            norm["identity"].update(table=row["values"].get("tablename"), form_record=rid,
                                    form_name=label_name(row["values"].get("namelabel")))
        options = {}
        for rid, row in by_table.get("workflow_selectitem", []):
            values = row["values"]
            option = {"field_id": values.get("fieldid"), "value": values.get("selectvalue"),
                      "name": text(row, "selectname"), "cancel": values.get("cancel"),
                      "isdefault": values.get("isdefault"), "listorder": values.get("listorder"),
                      "record": rid, "evidence": row["evidence"]}
            norm["select_options"].append(option)
            options.setdefault(values.get("fieldid"), []).append(option)
        for rid, row in by_table.get("workflow_billfield", []):
            values = row["values"]
            norm["fields"].append({"id": values.get("id"), "name": values.get("fieldname"),
                                   "label_id": values.get("fieldlabel"), "label": label_name(values.get("fieldlabel")),
                                   "html_type": values.get("fieldhtmltype"), "type": values.get("type"),
                                   "db_type": values.get("fielddbtype"), "bill_id": values.get("billid"),
                                   "detail_table": values.get("detailtable"), "display_order": values.get("dsporder"),
                                   "options": options.get(values.get("id"), []), "record": rid, "evidence": row["evidence"]})
        export_docs = [doc for doc in self.documents if doc["role"] == "export_values"]
        config_docs = [doc for doc in self.documents if doc["role"] == "configuration"]
        layout_profile_matches = bool(export_docs and config_docs) and (
            {doc["root_attributes"].get("datatype") for doc in export_docs} == {"mode"}
            and {doc["root_attributes"].get("cversion") for doc in config_docs} == {"9.00.2404.02"}
            and all(doc["root_attributes"].get("cversion") in {None, "9.00.2404.02"} for doc in export_docs)
            and all(doc["root_attributes"].get("datatype") in {None, "mode"} for doc in config_docs))
        metadata_evidence = [doc["evidence"] for doc in export_docs + config_docs]
        for rid, row in by_table.get("modehtmllayout", []):
            values = row["values"]
            candidate = LAYOUT_TYPE_CANDIDATES.get(values.get("type"))
            interpretation = {
                "status": "applied" if layout_profile_matches and candidate else "candidate" if candidate else "unmapped",
                "profile": LAYOUT_TYPE_PROFILE if layout_profile_matches else None,
                "candidate_profile": LAYOUT_TYPE_PROFILE, "sources": LAYOUT_TYPE_SOURCES,
                "metadata_evidence": metadata_evidence,
                "matched_metadata": {"datatype": "mode", "cversion": "9.00.2404.02"} if layout_profile_matches else None,
                "scope": "Checked local source snapshot and this exact export profile only; other versions require verification",
            }
            norm["layouts"].append({"id": values.get("id"), "name": text(row, "layoutname"),
                                    "type": values.get("type"),
                                    "type_name": candidate if layout_profile_matches and candidate else "未知",
                                    "type_name_candidate": candidate, "type_interpretation": interpretation,
                                    "is_default": values.get("isdefault"), "record": rid, "evidence": row["evidence"],
                                    "decoded_columns": list(row["decoded"])})
            if candidate and not layout_profile_matches:
                self.warnings.append({"code": "layout_type_unverified", "record": rid,
                                      "evidence": row["column_metadata"].get("type", {}).get("evidence", row["evidence"])})
        for rid, row in self.records.items():
            for key in row["values"]:
                if key.casefold() in SCRIPT_COLUMNS:
                    decoded = row["decoded"].get(key, {})
                    norm["scripts"].append({"record": rid, "column": key, "status": decoded.get("status", "absent"),
                                            "encoding": decoded.get("encoding"), "input_sha256": decoded.get("input_sha256"),
                                            "evidence": row["column_metadata"][key]["evidence"]})
        return norm


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def analyze_module(input_path, output_dir, limits=None) -> dict:
    """Parse a local ZIP, then write four portable JSON files; return a small summary."""
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in limits.values()):
        raise ModuleParseError("All parser limits must be positive integers")
    source, output = Path(input_path).resolve(), Path(output_dir)
    if not output.is_absolute():
        raise ModuleParseError("Output directory must be an absolute path")
    output = output.resolve()
    if not source.is_file():
        raise ModuleParseError("Input must be an existing ZIP file")
    if source.stat().st_size > limits["max_archive_bytes"]:
        raise ModuleParseError("Input archive exceeds configured byte limit")
    with source.open("rb") as handle:
        data = handle.read(limits["max_archive_bytes"] + 1)
    size = len(data)
    if size > limits["max_archive_bytes"]:
        raise ModuleParseError("Input archive exceeds configured byte limit")
    reader, members = _Reader(), []
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            infos = _validate_members(archive, limits)
            for info in infos:
                entry = {"name": info.filename, "size": info.file_size, "compressed_size": info.compress_size,
                         "crc32": f"{info.CRC:08x}", "is_directory": info.is_dir()}
                if info.is_dir():
                    entry["status"] = "directory"
                else:
                    # Reading to EOF verifies CRC; a byte cap also guards metadata inconsistencies.
                    with archive.open(info, "r") as handle:
                        payload = handle.read(limits["max_member_bytes"] + 1)
                    if len(payload) > limits["max_member_bytes"] or len(payload) != info.file_size:
                        raise ModuleParseError(f"ZIP member size is inconsistent or excessive: {info.filename}")
                    entry["sha256"] = sha256(payload)
                    if info.filename.casefold().endswith(".xml"):
                        root = _safe_xml(payload, info.filename, limits)
                        reader.document(root, info.filename)
                        entry["status"] = "parsed_xml"
                        entry["xml_encoding"] = root.getroottree().docinfo.encoding
                    else:
                        entry["status"] = "hashed_only"
                members.append(entry)
    except (BadZipFile, LargeZipFile, RuntimeError, NotImplementedError, EOFError) as error:
        raise ModuleParseError(f"Cannot safely read ZIP: {error}") from error
    if not reader.documents:
        raise ModuleParseError("Archive contains no XML documents")
    if not any(doc["role"] == "export_values" for doc in reader.documents):
        reader.warnings.append({"code": "missing_data_xml", "message": "No main export data.xml; identity and fields may be incomplete"})
    norm = reader.normalized()
    module = {"schema_version": SCHEMA_VERSION, "analyzer_version": TOOL_VERSION,
              "runtime_verified": False, "input_sha256": sha256(data),
              "limitations": ["offline_export_only", "no_database_or_runtime_validation", "no_execution", "empty_section_is_not_proof_of_runtime_absence", "overrides_not_merged", "unknown_sections_retained"],
              "documents": reader.documents, "records": reader.records,
              "normalized": norm, "warnings": reader.warnings}
    evidence = {"schema_version": SCHEMA_VERSION, "input_sha256": sha256(data),
                "location_contract": "line is the 1-based original XML start line; xpath identifies the node in the original member; members are identified and hashed by manifest.json",
                "items": reader.evidence}
    inventory = {"schema_version": SCHEMA_VERSION, "input_sha256": sha256(data), "tables": reader.inventory}
    outputs = {"module.json": _json_bytes(module), "evidence.json": _json_bytes(evidence),
               "table-inventory.json": _json_bytes(inventory)}
    # Do not overwrite the original source through an output name or symlink.
    for name in (*outputs, "manifest.json"):
        destination = output / name
        if destination.is_symlink() or (destination.exists() and destination.samefile(source)):
            raise ModuleParseError(f"Unsafe output destination: {destination}")
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        (output / name).write_bytes(payload)
    manifest = {"schema_version": SCHEMA_VERSION, "analyzer": "oa-module-analyzer",
                "analyzer_version": TOOL_VERSION, "runtime_verified": False,
                "input": {"name": source.name, "size": size, "sha256": sha256(data)},
                "limits": limits, "members": members,
                "outputs": {name: sha256(payload) for name, payload in outputs.items()},
                "manifest_hash_note": "Manifest cannot contain its own hash; hash this file separately when distributing results"}
    (output / "manifest.json").write_bytes(_json_bytes(manifest))
    return {"status": "ok", "analyzer_version": TOOL_VERSION, "runtime_verified": False,
            "output": str(output), "input_sha256": sha256(data),
            "identity": norm["identity"], "members": len(members),
            "sections": len(reader.inventory), "records": len(reader.records),
            "fields": len(norm["fields"]), "layouts": len(norm["layouts"]),
            "warnings": len(reader.warnings), "files": [*outputs, "manifest.json"]}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Local Weaver module export ZIP")
    parser.add_argument("--output", required=True, help="Absolute directory for four JSON artifacts")
    args = parser.parse_args(argv)
    try:
        summary = analyze_module(args.input, args.output)
    except (ModuleParseError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
