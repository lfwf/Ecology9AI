"""Bounded, non-executing input decoding with explicit evidence locations."""

import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from lxml import etree


class ParseError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Limits:
    max_archive_bytes: int = 64 * 1024 * 1024
    max_xml_bytes: int = 32 * 1024 * 1024
    max_entries: int = 256
    max_total_uncompressed: int = 128 * 1024 * 1024
    max_ratio: int = 1000


# Interpretation coverage, not a whitelist for discovering export tables.
SUPPORTED = {
    "workflow_base", "workflow_type", "workflow_bill", "workflow_billfield",
    "workflow_billdetailtable", "workflow_nodebase", "workflow_flownode",
    "workflow_nodelink", "workflow_nodegroup", "workflow_groupdetail",
    "workflow_hrmoperator", "workflow_nodeform", "workflow_nodeformgroup",
    "workflow_selectitem", "workflow_viewattrlinkage", "workflow_formula_htmllayout",
    "workflow_formula", "workflow_addinoperate", "workflow_function_manage",
    "workflow_requestwithdraw", "workflow_code", "workflow_coderegulate",
    "workflow_codeseq", "workflow_datainput_entry", "workflow_datainput_main",
    "workflow_datainput_table", "workflow_datainput_field", "workflow_nodehtmllayout",
    "workflow_bdf_dataranage", "workflow_browdef", "workflow_browdef_field",
    "workflowactionset", "workflowactionview", "sapactionset", "hrmresource",
    "hrmdepartment", "hrmroles", "hrmrolemembers", "hrmjobtitles", "hrmsubcompany",
    "htmllabelinfo", "htmllabelindex",
}
PERSONNEL_FIELDS = {
    "hrmresource": {"id", "lastname", "departmentid", "jobtitle", "subcompanyid1", "managerid", "status"},
    "hrmdepartment": {"id", "departmentname", "supdepid", "subcompanyid1"},
    "hrmroles": {"id", "rolesmark", "rolesname"},
    "hrmrolemembers": {"id", "roleid", "resourceid", "rolelevel", "alllevel"},
    "hrmjobtitles": {"id", "jobtitlename", "jobtitlemark"},
    "hrmsubcompany": {"id", "subcompanyname", "supsubcomid"},
}


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _tag(element):
    return element.tag.rsplit("}", 1)[-1].casefold() if isinstance(element.tag, str) else ""


def _attrs(element):
    return {k.casefold(): v for k, v in element.attrib.items()}


def _name(info):
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("gbk")
        except (UnicodeError, LookupError):
            pass
    return name.replace("\\", "/")


def _archive_xml(data, limits):
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_entries or sum(x.file_size for x in infos) > limits.max_total_uncompressed:
                raise ParseError("ARCHIVE_LIMIT", "压缩包条目数或总解压大小超过限制")
            entries, candidates, seen = [], [], set()
            for info in infos:
                name = _name(info)
                parts = PurePosixPath(name).parts
                if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in parts or stat.S_ISLNK(info.external_attr >> 16):
                    raise ParseError("UNSAFE_ARCHIVE_PATH", "压缩包包含不安全路径或符号链接")
                key = name.casefold()
                if key in seen:
                    raise ParseError("DUPLICATE_ENTRY", "压缩包存在重复或大小写冲突的文件名")
                seen.add(key)
                if info.file_size > limits.max_total_uncompressed or (info.file_size > 1024 * 1024 and info.file_size > max(info.compress_size, 1) * limits.max_ratio):
                    raise ParseError("ARCHIVE_LIMIT", "压缩包条目大小或压缩率超过限制")
                entries.append({"name": name, "size_bytes": info.file_size, "compressed_bytes": info.compress_size,
                                "crc": info.CRC, "content_read": False})
                if not info.is_dir() and name.casefold().endswith(".xml"):
                    candidates.append((info, entries[-1]))
            if not candidates:
                if any(x["name"].casefold().endswith(".exml") for x in entries):
                    raise ParseError("EXML_UNSUPPORTED", "EXML 容器加密不是布局脚本编码，需要单独的解密资料")
                raise ParseError("XML_MISSING", "压缩包中没有 XML 流程定义")
            if len(candidates) != 1:
                raise ParseError("MULTIPLE_XML", "压缩包含多个 XML，请分别提供定义，避免合并错误的配置")
            info, entry = candidates[0]
            if info.file_size > limits.max_xml_bytes:
                raise ParseError("ARCHIVE_LIMIT", "XML 声明大小超过限制")
            with archive.open(info) as stream:
                xml = stream.read(limits.max_xml_bytes + 1)
            if len(xml) > limits.max_xml_bytes:
                raise ParseError("ARCHIVE_LIMIT", "XML 实际解压大小超过限制")
            entry["content_read"] = True
            return xml, entries
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError) as error:
        raise ParseError("BAD_ARCHIVE", f"不能读取压缩包或 CRC 检查失败：{error}") from error


def _decode_field(value):
    raw = value.encode("utf-8")
    info = {"raw_text_sha256": _hash(raw), "assumption": "内层使用 JVM 默认字符集；离线先试 UTF-8，再试 GB18030"}
    try:
        decoded = base64.b64decode(re.sub(r"\s+", "", value), validate=True)
        info["decoded_bytes_sha256"] = _hash(decoded)
        for encoding in ("utf-8", "gb18030"):
            try:
                text = decoded.decode(encoding)
                info.update(status="decoded", encoding=encoding)
                return text, info
            except UnicodeError:
                continue
        raise ValueError("无法按支持的候选字符集解码")
    except (ValueError, UnicodeError) as error:
        info.update(status="failed", error=str(error))
        return value, info


def load_export(path, *, limits=None):
    """Read an export without extraction, network access, imports, or evaluation."""
    path, limits = Path(path), limits or Limits()
    try:
        with path.open("rb") as stream:
            data = stream.read(limits.max_archive_bytes + 1)
    except OSError as error:
        raise ParseError("INPUT_IO", f"不能读取输入文件：{error}") from error
    if len(data) > limits.max_archive_bytes:
        raise ParseError("INPUT_LIMIT", "输入文件超过大小限制")
    if path.suffix.casefold() == ".exml":
        raise ParseError("EXML_UNSUPPORTED", "EXML 加密容器需要独立解密资料")
    if zipfile.is_zipfile(BytesIO(data)):
        xml, entries = _archive_xml(data, limits)
    else:
        xml, entries = data, []
        if path.suffix.casefold() in {".wewf", ".zip"}:
            raise ParseError("BAD_ARCHIVE", "文件不是有效 ZIP 流程导出包")
    if len(xml) > limits.max_xml_bytes:
        raise ParseError("INPUT_LIMIT", "XML 超过大小限制")
    try:
        root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False))
    except (etree.XMLSyntaxError, ValueError) as error:
        raise ParseError("BAD_XML", f"不能解析 XML：{error}") from error
    if root.getroottree().docinfo.doctype:
        raise ParseError("UNSAFE_XML", "流程 XML 不允许 DTD 或实体声明")
    elements = [x for x in root.iter() if _tag(x) == "element"]
    table_nodes = [x for x in root.iter() if _tag(x) == "table"]
    if not table_nodes:
        raise ParseError("NOT_WORKFLOW_EXPORT", "XML 中没有流程配置 TABLE 记录")
    inventory, element_inventory, table_inventory, tables, issues = [], {}, {}, {}, []
    for element in elements:
        attrs = _attrs(element)
        name = attrs.get("tablename", "").casefold() or attrs.get("id", "").casefold()
        item = {"element_id": attrs.get("id", ""), "table": name, "count": 0,
                "present": True, "supported": name in SUPPORTED, "xml_line": element.sourceline,
                "field_names": [], "metadata": dict(element.attrib)}
        inventory.append(item)
        element_inventory[element] = item
        table_inventory[(element, name)] = item
        tables.setdefault(name, [])
    node_refs = {}
    retained_count = 0
    for table in table_nodes:
        meta = _attrs(table)
        if meta.get("id", "").casefold() == "$uid_log_table$":
            continue
        ancestor = table.getparent()
        while ancestor is not None and _tag(ancestor) != "element":
            ancestor = ancestor.getparent()
        declaration = element_inventory.get(ancestor)
        name = meta.get("tablename", "").casefold() or (declaration["table"] if declaration else "_unassigned")
        item = table_inventory.get((ancestor, name))
        if item is None:
            item = {"element_id": declaration["element_id"] if declaration else "", "table": name, "count": 0, "present": True,
                    "supported": name in SUPPORTED, "xml_line": table.sourceline, "field_names": [],
                    "metadata": dict(table.attrib), "nested_table": True}
            inventory.append(item)
            table_inventory[(ancestor, name)] = item
        item["count"] += 1
        fields = [x for x in table if _tag(x) == "field"]
        field_names = [_attrs(x).get("fieldname", "").casefold() for x in fields]
        item["field_names"] = sorted(set(item["field_names"]) | set(field_names))
        # Export metadata tables can contain a complete signed license. Keep
        # their inventory only. Other HRM profile tables are also minimized.
        if name.startswith("$") or meta.get("id", "").startswith("$"):
            item["excluded"] = "export_metadata_values"
            continue
        if name.startswith("hrm") and name not in PERSONNEL_FIELDS:
            item["excluded"] = "unneeded_personnel_profile"
            continue
        retained_count += 1
        ref = f"ev{retained_count:06}"
        clobs = {x.strip().casefold() for x in re.split(r"[,，]", meta.get("clobcolumn", "")) if x.strip()}
        values, decodings = {}, {}
        for field in fields:
            fa = _attrs(field)
            key = fa.get("fieldname", "").casefold()
            if name in PERSONNEL_FIELDS and key not in PERSONNEL_FIELDS[name]:
                continue
            value = "".join(field.itertext()) if fa.get("fieldtext", "").casefold() == "y" else fa.get("fieldvalue", "")
            if value and (key in clobs or fa.get("field_encrypt", "").casefold() == "y"):
                value, decoding = _decode_field(value)
                decoding["xml_line"] = field.sourceline
                decodings[key] = decoding
                if decoding["status"] == "failed":
                    issues.append({"code": "FIELD_DECODE_FAILED", "message": f"{name}.{key} 解码失败，保留原始值", "source_refs": [ref]})
            if key in values:
                issues.append({"code": "DUPLICATE_FIELD", "message": f"{name}.{key} 重复定义，末值被保留", "source_refs": [ref]})
            values[key] = value
        parent = table.getparent()
        while parent is not None and parent not in node_refs:
            parent = parent.getparent()
        record = {"values": values, "meta": dict(table.attrib), "ref": ref,
                  "line": table.sourceline, "parent_ref": node_refs.get(parent),
                  "element_id": item["element_id"], "decodings": decodings}
        node_refs[table] = ref
        tables.setdefault(name, []).append(record)
    return {
        "source": {"name": path.name, "sha256": _hash(data), "size_bytes": len(data),
                   "xml_sha256": _hash(xml), "encoding": root.getroottree().docinfo.encoding,
                   "archive_entries": entries},
        "tables": tables, "inventory": inventory, "issues": issues,
        "attachments": [x for x in entries if not x["content_read"]],
    }
