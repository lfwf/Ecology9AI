"""Normalize exported configuration without contacting or executing OA.

The export contains configuration, not proof of deployed behaviour. In
particular permissions, operator snapshots and stored linkage enums remain
separate from their eventual runtime effects.
"""

from copy import deepcopy
import json
import re


PROFILE = "weaver-e9-local-2026-10-23"
NODE_TYPES = {"0": "创建", "1": "审批", "2": "提交", "3": "归档",
              "4": "传阅", "5": "等待", "6": "自动处理"}
OPERATOR_TYPES = {"2": "role", "3": "person", "5": "form_field", "17": "creator"}
SIGN_TYPES = {"0": "非会签", "1": "会签", "2": "依次逐个",
              "3": "抄送无需提交", "4": "抄送需提交"}
LINKAGE_TYPES = {"1": "editable", "2": "mandatory", "3": "readonly",
                 "4": "hidden_content", "5": "hidden_row"}
LINKAGE_RUNTIME = {"1": 2, "2": 3, "3": 1}
SECTIONS = {
    "nodes": ("workflow_flownode", "workflow_nodebase"),
    "links": ("workflow_nodelink",), "fields": ("workflow_billfield",),
    "permissions": ("workflow_nodeform",),
    "detail_permissions": ("workflow_nodeformgroup",),
    "operator_groups": ("workflow_nodegroup", "workflow_groupdetail", "workflow_hrmoperator"),
    "options": ("workflow_selectitem",),
    "formulas": ("workflow_formula_htmllayout", "workflow_formula"),
    "linkages": ("workflow_viewattrlinkage",),
    "data_inputs": ("workflow_datainput_entry",),
    "actions": ("workflow_addinoperate",),
    "layouts": ("workflow_nodehtmllayout",),
    "code_rules": ("workflow_code", "workflow_coderegulate", "workflow_codeseq"),
    "withdrawal": ("workflow_requestwithdraw",),
    "detail_tables": ("workflow_billdetailtable",),
}


def _value(record, *names):
    values = record.get("values", {})
    for name in names:
        value = values.get(name, "")
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _refs(*records):
    result = []
    for record in records:
        if not record:
            continue
        items = record.get("source_refs", []) or ([record["ref"]] if record.get("ref") else [])
        for ref in items:
            if ref not in result:
                result.append(ref)
    return result


def _record(record, **attributes):
    return {**attributes, "raw": deepcopy(record.get("values", {})), "source_refs": _refs(record)}


def _issue(issues, code, message, *records):
    issues.append({"code": code, "message": message, "source_refs": _refs(*records)})


def _flag(record, key, issues, *, blank=False):
    value = _value(record, key).casefold()
    if value in {"1", "y", "yes", "true"}:
        return True
    if value in {"0", "n", "no", "false"}:
        return False
    if not value:
        return blank
    _issue(issues, "unknown_enum", f"{key}={value} 的布尔含义未识别", record)
    return None


def _ids(value):
    return [x for x in re.split(r"[,;，\s]+", value) if x]


def _layout(record, issues):
    values = record.get("values", {})
    result = _record(record, id=_value(record, "id"), node_id=_value(record, "nodeid"),
                     name=_value(record, "layoutname", "name"),
                     active=_flag(record, "isactive", issues, blank=None),
                     surface={"0": "desktop", "1": "mobile"}.get(_value(record, "type"), "unknown"),
                     type=_value(record, "type"), placements=[], placements_known=False,
                     tables=[])
    # Script extraction uses original archive records. Avoid duplicating large
    # executable-source strings in every normalized permission/layout record.
    result["raw"] = {k: v for k, v in result["raw"].items()
                     if k not in {"datajson", "scripts", "scriptstr", "initscripts", "html"}}
    text = values.get("datajson", "")
    if not text:
        result["parse_status"] = "missing"
        return result
    try:
        design = json.loads(text)
    except (ValueError, TypeError) as error:
        result["parse_status"] = "unsupported"
        _issue(issues, "layout_parse_failed", f"布局 datajson 不能解析：{error}", record)
        return result
    form_design = design.get("eformdesign") if isinstance(design, dict) else None
    tables = form_design.get("etables") if isinstance(form_design, dict) else None
    if not isinstance(tables, dict):
        result["parse_status"] = "unsupported"
        _issue(issues, "layout_shape_unsupported", "布局没有已识别的 eformdesign.etables", record)
        return result
    result.update(parse_status="parsed", placements_known=True)
    for table_name, table in tables.items():
        if not isinstance(table, dict):
            _issue(issues, "layout_shape_unsupported", f"布局表 {table_name} 结构未识别", record)
            result["placements_known"] = False
            continue
        result["tables"].append({"name": table_name,
                                 "attributes": deepcopy({k: v for k, v in table.items() if k != "ec"}),
                                 "source_refs": _refs(record)})
        cells = table.get("ec", [])
        if isinstance(cells, dict):
            cells = list(cells.values())
        if not isinstance(cells, list):
            result["placements_known"] = False
            continue
        for cell in cells:
            # In this E-Design profile etype2 is a field label, etype29 a
            # decoration, and etype3 the actual field control. Labels cannot
            # establish whether the corresponding input is present/hidden.
            if not isinstance(cell, dict) or not cell.get("field") or str(cell.get("etype")) != "3":
                continue
            coords = str(cell.get("id", "")).split(",")
            hidden = []
            if len(coords) == 2:
                rowattrs, colattrs = table.get("rowattrs", {}), table.get("colattrs", {})
                row = rowattrs.get(f"row_{coords[0]}", {}) if isinstance(rowattrs, dict) else {}
                col = colattrs.get(f"col_{coords[1]}", {}) if isinstance(colattrs, dict) else {}
                row = row if isinstance(row, dict) else {}
                col = col if isinstance(col, dict) else {}
                if str(row.get("hide", "")).casefold() in {"y", "1", "true"}:
                    hidden.append("row")
                if str(col.get("hide", "")).casefold() in {"y", "1", "true"}:
                    hidden.append("column")
            result["placements"].append({"field_id": str(cell["field"]), "table": table_name,
                                          "cell": str(cell.get("id", "")), "hidden": hidden,
                                          "label": str(cell.get("evalue", "")),
                                          "raw": deepcopy(cell), "source_refs": _refs(record)})
    return result


def _layout_permissions(node_id, field_id, layouts):
    result = []
    for layout in layouts:
        if layout["node_id"] != node_id or layout["active"] is not True:
            continue
        placements = [p for p in layout["placements"] if p["field_id"] == field_id]
        result.append({"id": layout["id"], "layout_id": layout["id"], "surface": layout["surface"],
                       "placement": "present" if placements else "absent" if layout["placements_known"] else "unknown",
                       "hidden": list(dict.fromkeys(x for p in placements for x in p["hidden"])),
                       "placements": deepcopy(placements), "source_refs": list(layout["source_refs"])})
    return result


def normalize(bundle, *, language="7"):
    """Return independently scoped workflows; never mutate the archive bundle."""
    tables = bundle.get("tables", {})
    by_ref = {r.get("ref"): r for rows in tables.values() for r in rows if r.get("ref")}
    bases = tables.get("workflow_base", [])
    labels = {(_value(r, "indexid", "id"), _value(r, "languageid")): r
              for r in tables.get("htmllabelinfo", [])}
    node_bases = {_value(r, "id", "nodeid"): r for r in tables.get("workflow_nodebase", [])}
    bills = {_value(r, "id"): r for r in tables.get("workflow_bill", [])}
    categories = {_value(r, "id"): r for r in tables.get("workflow_type", [])}
    roles = {_value(r, "id"): r for r in tables.get("hrmroles", [])}
    results = []
    for base in bases:
        workflow_id, form_id = _value(base, "id"), _value(base, "formid")
        issues = []
        flow = _record(base, id=workflow_id, name=_value(base, "workflowname", "name"),
                       form_id=form_id, category=_value(base, "workflowtype"),
                       interpretation_profile=PROFILE, issues=issues)
        category = categories.get(flow["category"])
        flow["category_name"] = _value(category or {}, "typename", "workflowtypename", "name")
        flow["source_refs"] = _refs(base, category, bills.get(form_id))
        for section in SECTIONS:
            flow[section] = []
        node_rows = [r for r in tables.get("workflow_flownode", []) if _value(r, "workflowid") == workflow_id]
        node_ids = {_value(r, "nodeid") for r in node_rows}
        # A nodebase with an explicit workflow scope can describe an isolated
        # node even when its flownode record was omitted by an export.
        for r in tables.get("workflow_nodebase", []):
            if _value(r, "workflowid") == workflow_id and _value(r, "id") not in node_ids:
                node_ids.add(_value(r, "id"))
                node_rows.append({"values": {"nodeid": _value(r, "id"), "workflowid": workflow_id},
                                  "ref": r.get("ref")})
        for record in node_rows:
            node_id, kind = _value(record, "nodeid"), _value(record, "nodetype")
            info = node_bases.get(node_id, {})
            node = _record(record, id=node_id, name=_value(info, "nodename", "name"),
                           type=kind, type_name=NODE_TYPES.get(kind, "未知"),
                           base_raw=deepcopy(info.get("values", {})),
                           signature={"required_mode": _value(record, "issignmustinput"),
                                      "operation_types": _ids(_value(record, "signmustinputtype")),
                                      "runtime_verified": False})
            node["source_refs"] = _refs(record, info)
            flow["nodes"].append(node)
            if kind not in NODE_TYPES:
                _issue(issues, "unknown_enum", f"节点类型 nodetype={kind} 未识别", record)
            if not info:
                _issue(issues, "missing_node_definition", f"节点 {node_id} 缺少 nodebase 定义", record)

        field_rows = [r for r in tables.get("workflow_billfield", [])
                      if _value(r, "billid", "formid") == form_id]
        field_ids = {_value(r, "id") for r in field_rows}
        owned_refs = set(_refs(base, bills.get(form_id), *node_rows, *field_rows))

        def scoped(record, *, field=False, node=False, form=False, fallback=False):
            wf = _value(record, "workflowid", "wfid", "flowid")
            if wf and wf != "-1":
                return wf == workflow_id
            frm = _value(record, "formid", "billid")
            if frm:
                return frm == form_id
            nid = _value(record, "nodeid")
            if nid:
                return nid in node_ids
            fid = _value(record, "fieldid")
            if field and fid:
                return fid in field_ids
            parent = record.get("parent_ref")
            visited = set()
            while parent and parent not in visited:
                if parent in owned_refs:
                    return True
                visited.add(parent)
                ancestor = by_ref.get(parent, {})
                if _value(ancestor, "workflowid", "wfid", "flowid") not in {"", "-1"}:
                    return _value(ancestor, "workflowid", "wfid", "flowid") == workflow_id
                parent = ancestor.get("parent_ref")
            return bool(fallback and len(bases) == 1)

        def rows(table, **kwargs):
            return [r for r in tables.get(table, []) if scoped(r, **kwargs)]

        for record in field_rows:
            label_record = labels.get((_value(record, "fieldlabel"), str(language)))
            detail = _value(record, "viewtype") == "1" or bool(_value(record, "detailtable"))
            field = _record(record, id=_value(record, "id"), name=_value(record, "fieldname"),
                            label=_value(label_record or {}, "labelname") or _value(record, "fieldlabel"),
                            label_id=_value(record, "fieldlabel"),
                            table=_value(record, "detailtable") if detail else _value(bills.get(form_id, {}), "tablename"),
                            db_type=_value(record, "fielddbtype"), html_type=_value(record, "fieldhtmltype"),
                            browser_type=_value(record, "type"), detail=detail)
            field["source_refs"] = _refs(record, label_record, bills.get(form_id))
            flow["fields"].append(field)
        for record in rows("workflow_billdetailtable", form=True):
            flow["detail_tables"].append(_record(record, id=_value(record, "id"),
                                                 name=_value(record, "tablename"),
                                                 order=_value(record, "orderid")))
        for record in rows("workflow_nodelink", node=True):
            link = _record(record, id=_value(record, "id"), from_node=_value(record, "nodeid", "fromnodeid"),
                           to_node=_value(record, "destnodeid", "tonodeid"),
                           name=_value(record, "linkname", "name"),
                           condition=record.get("values", {}).get("condition", ""),
                           is_reject=_flag(record, "isreject", issues))
            flow["links"].append(link)
            if link["from_node"] not in node_ids or link["to_node"] not in node_ids:
                _issue(issues, "dangling_node_reference", f"连线 {link['id']} 的端点没有节点定义", record)
        for record in rows("workflow_nodehtmllayout", node=True):
            flow["layouts"].append(_layout(record, issues))
        for node_id in node_ids:
            active = [r for r in flow["layouts"] if r["node_id"] == node_id and r["active"] is True]
            if len(active) > 1:
                _issue(issues, "layout_surface_ambiguity", f"节点 {node_id} 有多个生效布局，须按端口和视图分别判断", *active)

        permission_records = rows("workflow_nodeform", node=True)
        present_permissions = set()
        for record in permission_records:
            node_id, field_id = _value(record, "nodeid"), _value(record, "fieldid")
            present_permissions.add((node_id, field_id))
            view, edit, mandatory = (_flag(record, key, issues) for key in ("isview", "isedit", "ismandatory"))
            state = ("invisible" if view is False else "unknown" if view is None else
                     "mandatory" if mandatory is True else "editable" if edit is True else
                     "readonly" if edit is False else "unknown")
            flow["permissions"].append(_record(record, node_id=node_id, field_id=field_id,
                                                view=view, edit=edit, mandatory=mandatory,
                                                manual_edit_prohibited=_flag(record, "isonlyshow", issues),
                                                base_permission=state,
                                                layouts=_layout_permissions(node_id, field_id, flow["layouts"])))
            if field_id not in field_ids and not re.fullmatch(r"-\d+", field_id):
                _issue(issues, "dangling_field_reference", f"节点权限引用未定义字段 {field_id}", record)
        for node in flow["nodes"]:
            for field in flow["fields"]:
                if (node["id"], field["id"]) not in present_permissions:
                    flow["permissions"].append({"node_id": node["id"], "field_id": field["id"],
                                                "view": None, "edit": None, "mandatory": None,
                                                "manual_edit_prohibited": None, "base_permission": "missing",
                                                "layouts": _layout_permissions(node["id"], field["id"], flow["layouts"]),
                                                "raw": {}, "source_refs": _refs(node, field)})
        for record in rows("workflow_nodeformgroup", node=True):
            attributes = {name: _flag(record, key, issues) for name, key in
                          (("add", "isadd"), ("edit", "isedit"), ("delete", "isdelete"),
                           ("copy", "iscopy"), ("required", "isneed"))}
            flow["detail_permissions"].append(_record(record, node_id=_value(record, "nodeid"),
                                                       group_id=_value(record, "groupid"),
                                                       default_rows=_value(record, "defaultrows"), **attributes))

        for group in rows("workflow_nodegroup", node=True):
            group_id = _value(group, "id")
            item = _record(group, id=group_id, node_id=_value(group, "nodeid"),
                           name=_value(group, "groupname"), rules=[])
            details = [r for r in tables.get("workflow_groupdetail", []) if _value(r, "groupid") == group_id]
            for detail in details:
                detail_id, code = _value(detail, "id"), _value(detail, "type")
                joined = [r for r in tables.get("workflow_hrmoperator", [])
                          if _value(r, "groupdetailid") == detail_id and
                          _value(r, "groupid") in {"", group_id}]
                sign = _value(detail, "signorder") or next((_value(r, "signorder") for r in joined if _value(r, "signorder")), "")
                rule = _record(detail, id=detail_id, type=code, kind=OPERATOR_TYPES.get(code, "unknown"),
                               sign_order=sign, sign_type=SIGN_TYPES.get(sign, "未知"),
                               objects=[], runtime_members_verified=False,
                               hrm_operators=[_record(r) for r in joined])
                rule["source_refs"] = _refs(detail, *joined)
                object_ids = list(dict.fromkeys(_ids(_value(detail, "objid")) +
                                               [x for r in joined for x in _ids(_value(r, "objid"))]))
                for object_id in object_ids:
                    obj = {"id": object_id, "source_refs": _refs(detail, *joined)}
                    if code == "2":
                        role = roles.get(object_id, {})
                        members = [r for r in tables.get("hrmrolemembers", []) if _value(r, "roleid") == object_id]
                        obj.update(name=_value(role, "rolesmark", "rolesname"),
                                   member_ids=list(dict.fromkeys(_value(r, "resourceid") for r in members if _value(r, "resourceid"))),
                                   membership_scope="export_snapshot", runtime_members_verified=False,
                                   source_refs=_refs(detail, *joined, role, *members))
                    rule["objects"].append(obj)
                if code not in OPERATOR_TYPES:
                    _issue(issues, "unknown_enum", f"操作人 type={code} 未识别", detail)
                if sign not in SIGN_TYPES:
                    _issue(issues, "unknown_enum", f"操作人 signorder={sign} 未识别", detail, *joined)
                if code == "5" and any(x not in field_ids for x in object_ids):
                    _issue(issues, "dangling_field_reference", "操作人字段引用没有字段定义", detail)
                item["rules"].append(rule)
            item["source_refs"] = _refs(group, *item["rules"])
            flow["operator_groups"].append(item)

        for record in rows("workflow_selectitem", field=True):
            flow["options"].append(_record(record, id=_value(record, "id"), field_id=_value(record, "fieldid"),
                                            value=_value(record, "selectvalue"), label=_value(record, "selectname"),
                                            default=_flag(record, "isdefault", issues),
                                            cancelled=_flag(record, "cancel", issues)))
        for table in ("workflow_formula_htmllayout", "workflow_formula"):
            for record in rows(table, fallback=True):
                flow["formulas"].append(_record(record, id=_value(record, "id", "formulakey", "uuid"),
                                                node_id=_value(record, "nodeid"), layout_id=_value(record, "layoutid"),
                                                expression=_value(record, "formula", "formulatxt"),
                                                triggers=_value(record, "triggers"), table=table))
        for record in rows("workflow_viewattrlinkage", node=True):
            code = _value(record, "viewattr")
            flow["linkages"].append(_record(record, node_id=_value(record, "nodeid"),
                                             trigger_field=_value(record, "selectfieldid"),
                                             trigger_value=_value(record, "selectfieldvalue"),
                                             target_fields=_ids(_value(record, "changefieldids")),
                                             stored_code=code, meaning=LINKAGE_TYPES.get(code, "unknown"),
                                             runtime_code=LINKAGE_RUNTIME.get(code)))
            if code not in LINKAGE_TYPES:
                _issue(issues, "unknown_enum", f"属性联动 viewattr={code} 未识别", record)

        for record in rows("workflow_datainput_entry", fallback=True):
            code, entry_id = _value(record, "enable"), _value(record, "id")
            enabled = False if code == "1" else True if code in {"", "0"} else None
            if enabled is None:
                _issue(issues, "unknown_enum", f"数据带入 enable={code} 未识别", record)
            item = _record(record, id=entry_id, name=_value(record, "triggername", "name"),
                           enabled=enabled, trigger_field=_value(record, "triggerfieldname"), mappings=[], queries=[])
            mains = [r for r in tables.get("workflow_datainput_main", [])
                     if _value(r, "entryid") == entry_id or r.get("parent_ref") == record.get("ref")]
            gathered = [record]
            for main in mains:
                main_id = _value(main, "id")
                query = _record(main, id=main_id, data_source=_value(main, "datasourcename"),
                                condition=_value(main, "whereclause"), tables=[], mappings=[])
                children = [r for r in tables.get("workflow_datainput_table", [])
                            if _value(r, "datainputid") == main_id or r.get("parent_ref") == main.get("ref")]
                table_ids = {_value(r, "id") for r in children}
                query["tables"] = [_record(r, id=_value(r, "id"), name=_value(r, "tablename")) for r in children]
                mappings = [r for r in tables.get("workflow_datainput_field", [])
                            if _value(r, "datainputid") == main_id or
                            _value(r, "tableid") in table_ids or r.get("parent_ref") in set(_refs(main, *children))]
                for mapping in mappings:
                    mapped = _record(mapping, id=_value(mapping, "id"), target_field=_value(mapping, "pagefieldname"),
                                     source_field=_value(mapping, "dbfieldname"), table_id=_value(mapping, "tableid"),
                                     type=_value(mapping, "type"))
                    query["mappings"].append(mapped)
                    item["mappings"].append(deepcopy(mapped))
                gathered.extend([main, *children, *mappings])
                query["source_refs"] = _refs(main, *children, *mappings)
                item["queries"].append(query)
            item["source_refs"] = _refs(*gathered)
            flow["data_inputs"].append(item)
        for record in rows("workflow_addinoperate", fallback=True):
            marker = _value(record, "type") == "3" and _value(record, "customervalue") == "1"
            flow["actions"].append(_record(record, id=_value(record, "id"),
                                            node_id=_value(record, "objid") if _value(record, "isnode") == "1" else "",
                                            link_id=_value(record, "objid") if _value(record, "isnode") == "0" else "",
                                            type=_value(record, "type"), external_action_marker=marker,
                                            interface_id=None))
        for table in ("workflow_code", "workflow_coderegulate", "workflow_codeseq"):
            for record in rows(table, form=True):
                flow["code_rules"].append(_record(record, table=table, id=_value(record, "id")))
        flow["withdrawal"] = [_record(r, id=_value(r, "id")) for r in rows("workflow_requestwithdraw")]

        def check_field(value, record, context):
            # Stored references have field19572, 19572_1 or plain ID forms.
            field_id = re.sub(r"^field", "", value).split("_", 1)[0]
            if field_id and field_id not in field_ids and not re.fullmatch(r"-\d+", field_id):
                _issue(issues, "dangling_field_reference", f"{context}引用未定义字段 {field_id}", record)

        for section in ("layouts", "formulas", "linkages", "detail_permissions", "operator_groups", "actions"):
            for record in flow[section]:
                node_id = record.get("node_id")
                if node_id and node_id not in node_ids:
                    _issue(issues, "dangling_node_reference", f"{section}引用未定义节点 {node_id}", record)
        for record in flow["options"]:
            check_field(record["field_id"], record, "选项")
        for record in flow["linkages"]:
            check_field(record["trigger_field"], record, "属性联动触发项")
            for target in record["target_fields"]:
                check_field(target, record, "属性联动目标项")
        for record in flow["data_inputs"]:
            check_field(record["trigger_field"], record, "数据带入触发项")
            for mapping in record["mappings"]:
                check_field(mapping["target_field"], mapping, "数据带入映射项")
        # Presence is an export-level observation; there is no basis for
        # inferring that an absent table is a disabled configuration.
        present_tables = set(tables) | {i.get("table", "").casefold() for i in bundle.get("inventory", [])}
        flow["export_state"] = {section: "absent" if not any(t in present_tables for t in names) else
                                "present" if any(tables.get(t) for t in names) else "empty"
                                for section, names in SECTIONS.items()}
        results.append(flow)
    return results
