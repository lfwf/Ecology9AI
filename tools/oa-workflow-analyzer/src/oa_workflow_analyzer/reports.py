"""Offline reports for the public normalized result; source values are untrusted.

The report is a view of the evidence, not a second business-rule interpreter.
All formats share the same content model so PDF cannot silently omit a section.
ReportLab is deliberately imported only by ``render_pdf``.
"""

from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re


_COMPANIONS = (
    ("workflow.json", "完整配置及原始值"),
    ("evidence.json", "逐项证据"),
    ("missing-data.json", "待补资料"),
    ("agent-context.json", "智能体接入上下文"),
    ("manifest.json", "输出清单及指纹"),
)

_LABELS = {
    "id": "ID", "name": "名称", "form_id": "表单 ID", "category": "分类",
    "source_refs": "证据", "raw": "原始值", "issues": "记录问题",
    "node_id": "节点 ID", "field_id": "字段 ID", "layout_id": "布局 ID",
    "type": "类型原值", "type_name": "类型说明", "condition": "条件原文",
    "from_node": "起点", "to_node": "终点", "is_reject": "退回标记",
    "table": "表", "label": "显示名", "db_type": "数据库类型",
    "html_type": "控件类型", "browser_type": "浏览框类型", "detail": "明细字段",
    "view": "查看", "edit": "编辑", "mandatory": "必填",
    "manual_edit_prohibited": "禁止手工编辑", "base_permission": "基础权限",
    "layouts": "布局", "active": "生效", "enabled": "启用", "trigger_field": "触发字段",
    "mappings": "映射", "formula": "公式原文", "trigger": "触发条件",
    "placements": "布局位置", "rules": "规则", "value": "值",
    "line": "行号", "code": "代码", "message": "说明", "reason": "原因",
    "needed": "需要资料", "how_to_collect": "只读采集方式", "severity": "程度",
    "scope": "范围", "title": "标题", "decoding": "解码状态",
    "expression": "表达式原文", "triggers": "触发条件", "queries": "数据来源及查询条件",
    "source_field": "来源字段", "target_field": "目标字段", "target_fields": "目标字段",
    "stored_code": "导出存储码", "runtime_code": "已核验运行时码", "meaning": "已核验含义",
    "trigger_value": "触发值", "data_source": "数据源", "table_id": "来源表 ID",
}


def _text(value):
    if value is None:
        return "未提供"
    if value is True:
        return "是"
    if value is False:
        return "否"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def _records(value):
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, (list, tuple)) else []


def _payload_summary(value):
    return (f"[{len(value)} 字符；sha256={sha256(value.encode('utf-8')).hexdigest()}；"
            "完整原值见 evidence.json / workflow.json]")


def _readable(value):
    """Bound opaque payloads without changing the structured companion data."""
    if isinstance(value, str):
        return _payload_summary(value) if len(value) > 1000 else value
    if isinstance(value, dict):
        return {key: _readable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_readable(item) for item in value]
    return value


def _permission_matrix(workflow):
    """Keep every node/field pair, including system fields and unknown references."""
    nodes = {_text(node.get("id", "")): node.get("name", "未命名") for node in _records(workflow.get("nodes"))}
    fields = {_text(field.get("id", "")): field.get("label") or field.get("name") or "未命名" for field in _records(workflow.get("fields"))}
    cells, notes, note_keys = {}, [], {}
    states = {"editable": "可编辑", "mandatory": "必填", "readonly": "只读", "invisible": "隐藏（基础）", "missing": "缺记录", "unknown": "未知"}
    covered_raw = {"id", "uuid", "workflowid", "nodeid", "fieldid", "isview", "isedit", "ismandatory", "isonlyshow"}
    for record in _records(workflow.get("permissions")):
        node_id, field_id = _text(record.get("node_id", "")), _text(record.get("field_id", ""))
        nodes.setdefault(node_id, "未定义节点")
        fields.setdefault(field_id, "系统或未定义字段")
        state = record.get("base_permission", "未提供")
        parts = [states.get(state, _text(state))]
        if state != "missing":
            parts.append("V" + _text(record.get("view")) + " E" + _text(record.get("edit")) + " M" + _text(record.get("mandatory")))
        if record.get("manual_edit_prohibited") is True:
            parts.append("禁止手工编辑")
        elif record.get("manual_edit_prohibited") is None and state != "missing":
            parts.append("禁手编未知")
        for layout in _records(record.get("layouts")):
            surface = {"desktop": "桌面", "mobile": "移动"}.get(layout.get("surface"), _text(layout.get("surface", "布局")))
            flags = []
            for hidden in _records(layout.get("hidden")):
                flags.append({"row": "行隐藏", "column": "列隐藏"}.get(hidden, _text(hidden)))
            placement = layout.get("placement")
            if placement in ("absent", "unknown"):
                flags.append({"absent": "未布置", "unknown": "位置未知"}[placement])
            if flags:
                parts.append(surface + ":" + "/".join(flags))
        refs = record.get("source_refs") or []
        if refs:
            parts.append(",".join(_text(ref) for ref in refs))
        extra = {key: value for key, value in record.items() if key not in {"node_id", "field_id", "base_permission", "view", "edit", "mandatory", "manual_edit_prohibited", "layouts", "source_refs", "raw"}}
        raw = {key: value for key, value in (record.get("raw") or {}).items() if key not in covered_raw}
        if raw:
            extra["raw"] = raw
        if extra:
            signature = _text(extra)
            if signature not in note_keys:
                note_keys[signature] = "P" + str(len(notes) + 1)
                notes.append([note_keys[signature], extra])
            parts.append("补" + note_keys[signature])
        cells.setdefault((node_id, field_id), []).append("；".join(parts))
    matrices = []
    node_ids = list(nodes)
    # A wide export remains printable: each continuation repeats every field.
    for start in range(0, len(node_ids), 4):
        selected = node_ids[start:start + 4]
        headers = ["字段（ID）"] + [f"{_text(nodes[node_id])}（{node_id}）" for node_id in selected]
        rows = [[f"{_text(label)}（{field_id}）"] + ["\n".join(cells.get((node_id, field_id), ["未提供记录"])) for node_id in selected] for field_id, label in fields.items()]
        matrices.append((headers, rows))
    return matrices, notes


def _evidence_key(item):
    """Only primary-key coordinates; SQL/decoding metadata is not report prose."""
    metadata = {str(key).upper(): value for key, value in (item.get("metadata") or item.get("meta") or {}).items()}
    key, value = metadata.get("PRIMARYKEY"), metadata.get("PRIMARYKEYVALUE")
    if key and value is not None:
        return _text(key) + "=" + _text(_readable(value))
    values = item.get("values") or {}
    if key and key in values:
        return _text(key) + "=" + _text(_readable(values[key]))
    if "id" in values:
        return "id=" + _text(_readable(values["id"]))
    return "未提供主键"


def _md(value):
    """Escape source text in prose/table cells, including source Markdown links."""
    text = escape(_text(value), quote=False)
    for char in "\\`*[]|#!":
        text = text.replace(char, "\\" + char)
    # Underscores inside identifiers are literal in CommonMark and stay searchable.
    text = re.sub(r"(?<!\w)_|_(?!\w)", r"\\_", text)
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _safe_label(value):
    # Mermaid's quoted-label entities cannot end the label, edge, or code fence.
    return "".join(c if c.isalnum() or c == " " else f"#{ord(c)};" for c in _text(value))


def _diagram(workflow, source):
    salt = _text(source.get("sha256", "")) + ":" + _text(workflow.get("id", ""))

    def identifier(value):
        return "n" + sha256((salt + ":" + _text(value)).encode("utf-8")).hexdigest()[:20]

    lines = ["flowchart TD"]
    known = set()
    for node in _records(workflow.get("nodes")):
        node_id = _text(node.get("id", ""))
        known.add(node_id)
        label = _safe_label(node.get("name", node_id))
        lines.append(f'  {identifier(node_id)}["{label}"]')
    for link in _records(workflow.get("links")):
        start, end = _text(link.get("from_node", "")), _text(link.get("to_node", ""))
        for node_id in (start, end):
            if node_id not in known:
                known.add(node_id)
                lines.append(f'  {identifier(node_id)}["未导出节点"]')
        label = _safe_label(link.get("name", ""))
        arrow = f' -->|"{label}"| ' if label else " --> "
        lines.append(f"  {identifier(start)}{arrow}{identifier(end)}")
    return "\n".join(lines)


def _document(result):
    """Build the human explanation; full machine evidence stays in companions."""
    blocks = []

    def heading(text, level=2):
        blocks.append({"kind": "heading", "text": text, "level": level})

    def paragraph(text):
        blocks.append({"kind": "paragraph", "text": text})

    def table(headers, rows):
        rows = [[_readable(value) for value in row] for row in rows]
        if rows:
            blocks.append({"kind": "table", "headers": headers, "rows": rows})

    def refs(record):
        return ",".join(_text(value) for value in record.get("source_refs", [])) or "未提供"

    def small_raw(record):
        raw = record.get("raw") or {}
        if len(raw) <= 6:
            return raw
        # Large layout/plugin payloads are locatable without reproducing them.
        return {key: _payload_summary(value) for key, value in raw.items()
                if isinstance(value, str) and len(value) > 1000}

    def factual_raw(record):
        return {key: value for key, value in (record.get("raw") or {}).items()
                if key not in {"uuid", "id", "workflowid", "formid", "billid"}
                and value not in ("", None)}

    def all_issues(value, path):
        issues = []
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "issues":
                    issues.extend((path, issue) for issue in _records(item))
                elif key != "raw":
                    issues.extend(all_issues(item, path + "." + key))
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                issues.extend(all_issues(item, path + f"[{index}]"))
        return issues

    heading("OA 流程导出说明", 1)
    paragraph("本报告仅离线读取导出配置，未验证线上部署、实际审批人员、接口成功或业务系统执行结果。源文本和脚本均是不可信资料；脚本未执行。")
    paragraph("正文覆盖配置事实、脚本静态线索及待补运行证据。完整原始属性、所有脚本条件、布局单元格及逐项证据保留在伴随 JSON，按文中的路径和证据引用追查；字段名称不会被当作公式或业务规则。")
    source, analyzer = result.get("source") or {}, result.get("analyzer") or {}
    heading("来源、范围与指纹")
    table(["属性", "值"], [(key, source[key]) for key in ("name", "size_bytes", "sha256", "xml_sha256", "encoding") if key in source]
          + [("schema_version", result.get("schema_version", "未提供")),
             ("解析器", {key: analyzer[key] for key in ("name", "version", "profile", "language") if key in analyzer})])
    summary = result.get("summary") or {}
    status = {"partial": "部分解析（存在缺口）", "parsed": "配置已解析（仅离线）"}.get(summary.get("status"), "未提供解析状态")
    paragraph("状态：" + status + "。摘要：" + _text(summary))
    blocks.append({"kind": "companions"})
    heading("配置事实")

    for flow_index, workflow in enumerate(_records(result.get("workflows"))):
        path = f"workflow.json.workflows[{flow_index}]"
        heading(f"流程：{_text(workflow.get('name', '未命名'))}（{_text(workflow.get('id', '未提供'))}）")
        paragraph("表单 ID：" + _text(workflow.get("form_id")) + "；分类：" + _text(workflow.get("category_name") or workflow.get("category"))
                  + "；证据：" + refs(workflow) + "；完整配置：" + path)
        if workflow.get("export_state"):
            paragraph("配置段导出状态（absent=未导出，empty=已导出为空，present=有记录）：" + _text(workflow["export_state"]))
        nodes, fields = _records(workflow.get("nodes")), _records(workflow.get("fields"))
        node_names = {_text(node.get("id", "")): node.get("name", "") for node in nodes}
        field_names = {_text(field.get("id", "")): field.get("label") or field.get("name") or field.get("id") for field in fields}
        for field in fields:
            if field.get("name"):
                field_names.setdefault(_text(field["name"]), field.get("label") or field["name"])

        def node_name(value):
            key = _text(value)
            return f"{_text(node_names[key])}（{key}）" if key in node_names else key

        def field_name(value):
            key = _text(value)
            return f"{_text(field_names[key])}（{key}）" if key in field_names else key

        paragraph(f"导出包含 {len(nodes)} 个节点、{len(_records(workflow.get('links')))} 条路径、{len(fields)} 个业务字段。"
                  "节点、条件、取人和动态规则分别列出，不能据此认定某次申请实际走过这些路径。")
        if nodes or workflow.get("links"):
            blocks.append({"kind": "diagram", "text": _diagram(workflow, source)})
        heading("节点与签字配置", 3)
        table(["节点", "类型原值/说明", "签字配置原值", "证据"],
              [[node_name(node.get("id")), _text(node.get("type")) + "/" + _text(node.get("type_name")),
                node.get("signature", "未提供"), refs(node)] for node in nodes])
        links = _records(workflow.get("links"))
        if links:
            heading("路径、分支与退回", 3)
            table(["起点 → 终点", "名称", "条件原文", "退回标记", "证据"],
                  [[node_name(link.get("from_node")) + " → " + node_name(link.get("to_node")),
                    link.get("name", ""), link.get("condition", ""), link.get("is_reject"), refs(link)] for link in links])
        reject_keys = {"rejecttocreater", "rejectbackflag", "rejecttocreatenode", "isselectrejectnode",
                       "ischangrejectnode", "rejectablenodes", "takeback", "drawbackflag"}
        rejection = [[node_name(node.get("id")), {key: value for key, value in (node.get("raw") or {}).items()
                      if key in reject_keys and value not in ("", None)}, refs(node)] for node in nodes]
        rejection = [row for row in rejection if row[1]]
        if rejection:
            paragraph("退回与收回相关存储属性只列原值；未纳入已核验 profile 的代码不作业务解释。")
            table(["节点", "退回/收回属性原值", "证据"], rejection)

        heading("表单字段", 3)
        table(["ID", "显示名 / 字段名", "主/明细及表", "数据库类型", "控件/浏览框原码", "证据"],
              [[field.get("id"), _text(field.get("label")) + " / " + _text(field.get("name")),
                ("明细：" if field.get("detail") else "主表：") + _text(field.get("table")),
                field.get("db_type"), _text(field.get("html_type")) + "/" + _text(field.get("browser_type")), refs(field)] for field in fields])
        small_fields = [[field_name(field.get("id")), small_raw(field)] for field in fields if small_raw(field)]
        if small_fields:
            table(["字段", "补充小原值"], small_fields)
        if workflow.get("permissions"):
            heading("节点字段权限矩阵", 3)
            paragraph("V=查看，E=编辑，M=必填。每格保留基础权限、禁止手工编辑、布局行列隐藏/未布置和证据；缺记录不代表允许。"
                      "这些是静态配置，脚本还可能动态修改字段。完整权限及布局位置：" + path + ".permissions / .layouts。")
            matrices, notes = _permission_matrix(workflow)
            for headers, rows in matrices:
                table(headers, rows)
            # Only problems and unknown business codes belong in the main view.
            important = [row for row in notes if any(key != "raw" for key in row[1])
                         or any("unknown" in key.casefold() or "enum" in key.casefold() or "future" in key.casefold()
                                for key in (row[1].get("raw") or {}))]
            if important:
                table(["矩阵补充项", "未知代码或记录问题"], important)
            paragraph("补P编号中未展开的排序、排版等原始属性请按该格证据查 JSON；记录问题和未知业务代码仍列在本报告。")
        detail = _records(workflow.get("detail_permissions"))
        if detail:
            heading("明细权限", 3)
            table(["节点/明细组", "增/改/删/复制", "必需/默认行数", "证据"],
                  [[node_name(item.get("node_id")) + "/" + _text(item.get("group_id", item.get("detail_id"))),
                    "/".join(_text(item.get(key)) for key in ("add", "edit", "delete", "copy")),
                    _text(item.get("required")) + "/" + _text(item.get("default_rows")), refs(item)] for item in detail])

        groups = _records(workflow.get("operator_groups"))
        if groups:
            heading("操作人、会签与抄送", 3)
            paragraph("规则描述导出配置；角色成员属于导出快照，实际取人须核对请求和当前组织权限。")
            rows = []
            for group in groups:
                for rule in _records(group.get("rules")) or [{}]:
                    objects = []
                    for obj in _records(rule.get("objects")):
                        objects.append({"id": obj.get("id"), "name": obj.get("name"),
                                        "导出成员数": len(obj.get("member_ids", [])) if "member_ids" in obj else "未提供"})
                    rows.append([node_name(group.get("node_id")) + "/" + _text(group.get("name", group.get("id"))),
                                 _text(rule.get("kind", "未知")) + "（type=" + _text(rule.get("type")) + "）",
                                 rule.get("sign_type", rule.get("signorder", rule.get("sign_order", "未提供"))),
                                 objects or rule.get("objid", small_raw(rule)), refs(rule) if rule.get("source_refs") else refs(group)])
            table(["节点/操作组", "取人类型", "会签/抄送原值或说明", "配置对象", "证据"], rows)
        options = _records(workflow.get("options"))
        if options:
            heading("选项", 3)
            table(["字段", "存储值", "显示名", "默认/取消", "证据"],
                  [[field_name(item.get("field_id")), item.get("value"), item.get("label"),
                    _text(item.get("default")) + "/" + _text(item.get("cancelled")), refs(item)] for item in options])
        formulas = _records(workflow.get("formulas"))
        if formulas:
            heading("平台公式", 3)
            paragraph("只转录平台表达式，不从字段名补造计算规则。来源：" + path + ".formulas。")
            table(["节点/布局及来源表", "表达式原文", "触发配置与证据"],
                  [[node_name(item.get("node_id", "")) + "/" + _text(item.get("layout_id", "")) + "/" + _text(item.get("table", "")),
                    item.get("expression", item.get("formula", "")),
                    {"trigger": item.get("triggers", item.get("trigger", "")), "refs": refs(item)}] for item in formulas])
        linkages = _records(workflow.get("linkages"))
        if linkages:
            heading("属性联动", 3)
            paragraph("导出存储码与 WfForm 运行时码分别保留，不能混用。来源：" + path + ".linkages。")
            table(["节点/触发", "目标字段", "存储码/含义/运行时码", "证据"],
                  [[node_name(item.get("node_id", "")) + "；" + field_name(item.get("trigger_field", "")) + "="
                    + _text(item.get("trigger_value", item.get("condition", ""))),
                    [field_name(value) for value in item.get("target_fields", [item.get("target_field", "")])],
                    _text(item.get("stored_code", item.get("stored_attribute"))) + "/" + _text(item.get("meaning")) + "/" + _text(item.get("runtime_code")), refs(item)] for item in linkages])
        data_inputs = _records(workflow.get("data_inputs"))
        if data_inputs:
            heading("数据带入", 3)
            paragraph("启用状态由 profile 解读，禁用规则仍保留。匹配条件、数据源及映射均为配置事实，未执行查询。来源：" + path + ".data_inputs。")
            for entry in data_inputs:
                paragraph("规则：" + _text(entry.get("name", entry.get("id"))) + "（" + _text(entry.get("id"))
                          + "）；启用：" + _text(entry.get("enabled")) + "；触发字段：" + field_name(entry.get("trigger_field"))
                          + "；证据：" + refs(entry))
                table(["数据源/查询表", "查询或匹配条件", "证据"],
                      [[_text(query.get("data_source")) + "/" + _text([item.get("name", item.get("table")) for item in _records(query.get("tables"))]),
                        query.get("condition", ""), refs(query)] for query in _records(entry.get("queries"))])
                table(["目标字段", "来源字段", "来源表/映射类型", "证据"],
                      [[field_name(mapping.get("target_field", mapping.get("to", ""))), mapping.get("source_field", mapping.get("from", "")),
                        _text(mapping.get("table_id", "")) + "/" + _text(mapping.get("type", "")), refs(mapping)]
                       for mapping in _records(entry.get("mappings"))])
        actions = _records(workflow.get("actions"))
        if actions:
            heading("节点动作与接口标记", 3)
            paragraph("type=3/customervalue=1 是操作标记，不能当作接口 ID 或已调用成功的证据。实际定义和执行结果见待补资料。")
            table(["节点/路径", "类型/接口标记", "操作时机等原始配置", "证据"],
                  [[node_name(item.get("node_id", "")) + "/" + _text(item.get("link_id", "")),
                    _text(item.get("type", (item.get("raw") or {}).get("type"))) + "/" + _text(item.get("external_action_marker")),
                    factual_raw(item), refs(item)] for item in actions])
        code_rules = _records(workflow.get("code_rules"))
        if code_rules:
            heading("编号规则", 3)
            table(["来源表/规则 ID", "编号配置原值", "证据"],
                  [[_text(item.get("table", "")) + "/" + _text(item.get("id", "")),
                    factual_raw(item) or {key: value for key, value in item.items() if key not in ("source_refs", "id", "table", "raw")}, refs(item)] for item in code_rules])
        withdrawal = _records(workflow.get("withdrawal"))
        if withdrawal:
            heading("撤回及意见配置", 3)
            table(["配置原值", "证据"], [[factual_raw(item) or {key: value for key, value in item.items() if key not in ("source_refs", "raw")}, refs(item)] for item in withdrawal])
        layouts = _records(workflow.get("layouts"))
        if layouts:
            heading("布局及隐藏配置", 3)
            paragraph("节点权限矩阵已列隐藏和未布置标记；完整单元格、行列及生效布局保留在 " + path + ".layouts。")
            table(["布局/节点", "生效/端口", "字段位置数及隐藏", "证据"],
                  [[_text(item.get("id")) + "/" + node_name(item.get("node_id")),
                    _text(item.get("active")) + "/" + _text(item.get("surface")),
                    {"位置数": len(_records(item.get("placements"))),
                     "隐藏字段": [{field_name(place.get("field_id")): place.get("hidden")} for place in _records(item.get("placements")) if place.get("hidden")]},
                    refs(item)] for item in layouts])
            payloads = [[item.get("id"), small_raw(item)] for item in layouts if small_raw(item)]
            if payloads:
                table(["布局", "小原值或大载荷指纹（完整值见 evidence.json）"], payloads)
        issue_rows, seen = [], set()
        for issue_path, issue in all_issues(workflow, path):
            signature = _text(issue)
            if signature in seen:
                continue
            seen.add(signature)
            if isinstance(issue, dict):
                issue_rows.append([issue.get("code"), issue.get("message"), issue_path, refs(issue)])
            else:
                issue_rows.append(["未知", issue, issue_path, "未提供"])
        if issue_rows:
            heading("解析问题与未知代码", 3)
            table(["代码", "影响或说明", "JSON 路径", "证据"], issue_rows)

    heading("脚本静态线索")
    paragraph("仅静态分析源码，不能证明事件实际触发、请求成功、字段实际写入或接口副作用。事件入口和保守调用路径与平台公式分别保留；未列出的源码条件仍在 JSON 中。")
    scripts = _records(result.get("scripts"))
    if not scripts:
        paragraph("未提供可展示的脚本静态线索。")
    for index, script in enumerate(scripts):
        path = f"workflow.json.scripts[{index}]"
        heading("脚本 " + _text(script.get("id", index)), 3)
        paragraph("节点：" + _text(script.get("node_id")) + "；布局：" + _text(script.get("layout_id"))
                  + "；生效：" + _text(script.get("active")) + "；解码：" + _text(script.get("decoding"))
                  + "；证据：" + refs(script) + "；来源：" + path)
        analysis = script.get("analysis") or {}
        events = _records(analysis.get("events"))
        if events:
            table(["行号/事件操作", "命名函数及保守可达地址", "静态调用路径"],
                  [[_text(event.get("line")) + "/" + _text(event.get("operations", event.get("operation", ""))),
                    {"calls": event.get("calls", []), "reachable_endpoints": event.get("reachable_endpoints", [])},
                    event.get("endpoint_paths", [])] for event in events])
        calls = _records(analysis.get("network_calls"))
        if calls:
            table(["行号/函数", "请求地址原文", "动态地址表达式"],
                  [[_text(call.get("line")) + "/" + _text(call.get("function", "")), call.get("url", ""), call.get("expression", "")] for call in calls])
        for key, label, value_key in (("field_writes", "字段写入线索", "value"), ("attribute_changes", "属性变更线索", "attribute")):
            values = _records(analysis.get(key))
            if values:
                paragraph(label + "：仅列写入语句，不能据此认定执行结果。")
                table(["行号/函数", "目标字段", "值或属性原文"],
                      [[_text(item.get("line")) + "/" + _text(item.get("function", "")), item.get("target"), item.get(value_key, item.get("snippet", ""))] for item in values])
        functions = _records(analysis.get("functions"))
        if functions:
            if len(functions) <= 8:
                table(["行号", "函数名", "调用"], [[item.get("line"), item.get("name"), item.get("calls")] for item in functions])
            else:
                paragraph(f"识别到 {len(functions)} 个命名函数；事件路径涉及的函数已在上表列出。完整定义与调用关系：" + path + ".analysis.functions。")
        conditions = _records(analysis.get("conditions"))
        if conditions:
            if len(conditions) <= 8:
                table(["行号", "类型", "条件原文"], [[item.get("line"), item.get("kind"), item.get("text", item.get("snippet", ""))] for item in conditions])
            else:
                grouped = {}
                for condition in conditions:
                    grouped.setdefault(_text(condition.get("function", condition.get("kind", "未标注"))), []).append(condition.get("line"))
                paragraph(f"提取到 {len(conditions)} 条静态条件；各条件及上下文见 " + path + ".analysis.conditions。未根据条件名称推断业务结果。")
                table(["函数（若源码可定位）或条件类型", "条件数", "源码行号"], [[key, len(lines), lines] for key, lines in grouped.items()])
        warnings = _records(analysis.get("warnings"))
        if warnings:
            table(["静态分析限制代码", "说明"], [[item.get("code", "STATIC_LIMIT"), item.get("message", item)] if isinstance(item, dict) else ["STATIC_LIMIT", item] for item in warnings])
        text = script.get("text", "")
        if text and len(text) <= 2000:
            paragraph("经解析器脱敏的脚本文本（仅供阅读，不执行）：")
            blocks.append({"kind": "code", "text": _text(text)})
        elif text:
            paragraph("脚本全文 " + _payload_summary(text))

    heading("待补资料与运行证据")
    gaps = _records(result.get("gaps"))
    if not gaps:
        paragraph("未提供缺口条目；这不代表线上行为已验证。")
    grouped = {}
    for gap in gaps:
        key = (_text(gap.get("code")), _text(gap.get("category")), _text(gap.get("title")))
        grouped.setdefault(key, []).append(gap)
    for (code, category, title), items in grouped.items():
        heading(title + "（" + code + "）", 3)
        reasons = list(dict.fromkeys(_text(item.get("reason")) for item in items))
        needed = list(dict.fromkeys(_text(item.get("needed")) for item in items))
        collect = list(dict.fromkeys(_text(item.get("how_to_collect")) for item in items))
        paragraph("分类：" + category + "；范围：" + "、".join(dict.fromkeys(_text(item.get("scope")) for item in items))
                  + "；条目：" + ",".join(_text(item.get("id")) for item in items))
        table(["原因及影响", "需要补充", "只读采集方式"],
              [["；".join(reasons), "；".join(needed), "；".join(collect)]])
        paragraph("证据：" + ",".join(dict.fromkeys(ref for item in items for ref in item.get("source_refs", [])))
                  + "；逐项程度和范围见 missing-data.json。")
    if result.get("issues"):
        table(["全局解析问题"], [[item] for item in _records(result["issues"])])

    heading("导出覆盖与证据追查")
    inventory = _records(result.get("table_inventory"))
    counts = {}
    for item in inventory:
        if item.get("present") is False:
            state = "未导出"
        elif item.get("present") is True and item.get("count") == 0:
            state = "已导出为空"
        elif item.get("present") is True:
            state = "已导出有记录"
        else:
            state = "导出状态未知"
        support = {True: "已支持", False: "未支持"}.get(item.get("supported"), "支持情况未知")
        counts[(state, support)] = counts.get((state, support), 0) + 1
    table(["导出情况", "支持情况", "元素数"], [[state, support, count] for (state, support), count in counts.items()])
    unsupported = [item for item in inventory if item.get("supported") is False and item.get("count", 0)]
    if unsupported:
        table(["未支持且有记录的表", "记录数"], [[item.get("table"), item.get("count")] for item in unsupported])
    paragraph(f"证据文件含 {len(_records(result.get('evidence')))} 条记录。按 source_refs 到 evidence.json 查 ID、来源表、XML 行号、主键及完整值；"
              "表元素和元数据见 workflow.json.table_inventory，未知配置依赖见 missing-data.json。"
              "正文不重复所有证据、空表和原始载荷；大载荷保留字符数与 SHA-256。")
    return blocks


def render_markdown(result):
    """Render portable Markdown, including a safe, stable Mermaid graph."""
    output = []
    for block in _document(result):
        kind = block["kind"]
        if kind == "heading":
            output.append("#" * block["level"] + " " + _md(block["text"]))
        elif kind == "paragraph":
            output.append(_md(block["text"]))
        elif kind == "table":
            if not block["rows"]:
                continue
            output.append("| " + " | ".join(_md(v) for v in block["headers"]) + " |\n| " + " | ".join("---" for _ in block["headers"]) + " |\n" + "\n".join("| " + " | ".join(_md(v) for v in row) + " |" for row in block["rows"]))
        elif kind == "companions":
            output.append("伴随文件：" + "；".join(f"[{name}]({name})（{label}）" for name, label in _COMPANIONS))
        elif kind == "diagram":
            output.append("```mermaid\n" + block["text"] + "\n```")
        elif kind == "code":
            # Indented code cannot terminate its enclosure with source backticks.
            output.append("\n".join("    " + line for line in block["text"].splitlines()))
    return "\n\n".join(output) + "\n"


_CSS = """
body{font-family:'Microsoft YaHei',SimSun,sans-serif;color:#203142;background:#f5f7fa;line-height:1.65;margin:0}
main{max-width:1500px;margin:auto;padding:32px;background:white}h1,h2,h3{color:#183b56;overflow-wrap:anywhere}
h1{border-bottom:3px solid #187b8d;padding-bottom:12px}h2{margin-top:32px;border-bottom:1px solid #ccd9e2}
table{border-collapse:collapse;width:100%;font-size:13px;margin:14px 0;table-layout:fixed}
td,th{border:1px solid #d7e0e7;padding:7px;text-align:left;vertical-align:top;overflow-wrap:anywhere;white-space:pre-wrap}
th{background:#eaf2f6;color:#183b56}tr:nth-child(even){background:#f8fafc}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f8;padding:16px;border:1px solid #d7e0e7;font-size:12px}
a{color:#126d83}p{overflow-wrap:anywhere}nav{padding:12px;background:#eaf2f6}
@media print{body,main{background:white;margin:0;padding:0}main{max-width:none}h2,h3{break-after:avoid}tr{break-inside:avoid}thead{display:table-header-group}pre{font-size:9pt}a{color:inherit;text-decoration:none}table{font-size:9pt}}
"""


def render_html(result):
    """Render self-contained HTML; never interpolate source into tags or URLs."""
    body = []
    for block in _document(result):
        kind = block["kind"]
        if kind == "heading":
            level = block["level"]
            body.append(f"<h{level}>{escape(block['text'])}</h{level}>")
        elif kind == "paragraph":
            body.append("<p>" + escape(block["text"]) + "</p>")
        elif kind == "table" and block["rows"]:
            header = "".join("<th>" + escape(_text(v)) + "</th>" for v in block["headers"])
            rows = "".join("<tr>" + "".join("<td>" + escape(_text(v)) + "</td>" for v in row) + "</tr>" for row in block["rows"])
            body.append("<table><thead><tr>" + header + "</tr></thead><tbody>" + rows + "</tbody></table>")
        elif kind == "companions":
            body.append("<nav>伴随文件：" + "；".join(f'<a href="{name}">{name}</a>（{label}）' for name, label in _COMPANIONS) + "</nav>")
        elif kind == "code":
            body.append("<pre><code>" + escape(block["text"]) + "</code></pre>")
        # Offline HTML uses the node/edge tables instead of a JavaScript renderer.
    policy = "default-src 'none'; script-src 'none'; connect-src 'none'; img-src 'none'; font-src 'none'; style-src 'unsafe-inline'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'"
    return '<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="' + policy + '"><title>OA 流程导出说明</title><style>' + _CSS + '</style></head><body><main>' + "\n".join(body) + '</main></body></html>\n'


def _pdf_font(pdfmetrics, TTFont, UnicodeCIDFont):
    """Prefer an installed Chinese TrueType face, then built-in CJK CID fonts."""
    name = "OAReportCJK"
    if name in pdfmetrics.getRegisteredFontNames():
        return name
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [windows / "msyh.ttc", windows / "simsun.ttc", windows / "simhei.ttf", Path("/usr/share/fonts/truetype/arphic/uming.ttc"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]
    for candidate in candidates:
        if candidate.is_file():
            try:
                pdfmetrics.registerFont(TTFont(name, str(candidate), subfontIndex=0))
                return name
            except Exception:
                # Some TTC files use unsupported PostScript outlines.
                continue
    name = "STSong-Light"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(name))
    return name


def render_pdf(result, path):
    """Write a Chinese-readable PDF with lazy optional ReportLab imports.

    Uses flowable text for raw source, avoiding page-sized unsplittable code rows.
    There are no external fetches, scripts, office automation, or shell commands.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
    except ImportError as exc:
        raise RuntimeError("生成 PDF 需要可选依赖 ReportLab；请在工具使用的 Python 环境安装 reportlab，或不传 --pdf。") from exc

    font = _pdf_font(pdfmetrics, TTFont, UnicodeCIDFont)
    normal = ParagraphStyle("OA body", fontName=font, fontSize=8, leading=12, alignment=TA_LEFT, wordWrap="CJK", splitLongWords=True, spaceAfter=5)
    headings = {level: ParagraphStyle(f"OA h{level}", parent=normal, fontSize=size, leading=size + 6, spaceBefore=12, spaceAfter=8, keepWithNext=True, textColor=colors.HexColor("#183b56")) for level, size in ((1, 20), (2, 14), (3, 11))}
    table_header = ParagraphStyle("OA table header", parent=normal, fontSize=7, leading=10, spaceAfter=0, textColor=colors.HexColor("#183b56"))
    table_body = ParagraphStyle("OA table body", parent=normal, fontSize=7, leading=10, spaceAfter=0)

    def paragraph(value, style=normal):
        # ReportLab's paragraph parser receives only escaped text and our breaks.
        text = "".join(char for char in _text(value) if ord(char) >= 32 or char in "\n\t")
        return Paragraph(escape(text).replace("\n", "<br/>").replace("\t", "    "), style)

    target = Path(path)
    document = SimpleDocTemplate(str(target), pagesize=landscape(A4), leftMargin=30, rightMargin=30, topMargin=32, bottomMargin=32, title="OA 流程导出说明", author="oa-workflow-analyzer")
    story = []
    for block in _document(result):
        kind = block["kind"]
        if kind == "heading":
            story.append(paragraph(block["text"], headings[block["level"]]))
        elif kind == "paragraph":
            story.append(paragraph(block["text"]))
        elif kind == "companions":
            story.append(paragraph("伴随文件：" + "；".join(f"{name}（{label}）" for name, label in _COMPANIONS)))
        elif kind == "table" and block["rows"]:
            headers = block["headers"]
            rows = [[paragraph(value, table_header) for value in headers]]
            rows.extend([paragraph(value, table_body) for value in row] for row in block["rows"])
            widths = [document.width / len(headers)] * len(headers)
            if len(headers) == 2:
                widths = [document.width * .22, document.width * .78]
            elif headers == ["行号", "类型", "条件原文"]:
                widths = [document.width * .07, document.width * .13, document.width * .8]
            elif headers == ["证据 ID", "来源表", "行号", "主键"]:
                widths = [document.width * .12, document.width * .32, document.width * .07, document.width * .49]
            elif headers == ["行号", "函数名", "调用"]:
                widths = [document.width * .07, document.width * .23, document.width * .7]
            grid = LongTable(rows, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1, splitInRow=1)
            grid.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2f6")), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#cdd9e2")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            story.extend((grid, Spacer(1, 8)))
        elif kind == "code":
            # Each source line is independently splittable, including long literals.
            for line in block["text"].splitlines():
                story.append(paragraph(line or " "))

    def page_number(canvas, doc):
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#526b7c"))
        canvas.drawString(30, 17, "离线配置说明 · 未验证线上")
        canvas.drawRightString(doc.pagesize[0] - 30, 17, f"第 {doc.page} 页")

    document.build(story, onFirstPage=page_number, onLaterPages=page_number)
    return None
