"""Synthetic exports exercise semantics independently of any customer package."""
import copy
import json
import unittest

from oa_workflow_analyzer.normalize import normalize


def bundle(**tables):
    counter = 0
    result = {"tables": {}, "inventory": [], "issues": []}
    for table, rows in tables.items():
        records = []
        for row in rows:
            counter += 1
            records.append({"values": {k.lower(): str(v) for k, v in row.items()},
                            "meta": {}, "ref": f"ev{counter:06}", "line": counter})
        result["tables"][table.lower()] = records
        result["inventory"].append({"table": table.lower(), "count": len(rows),
                                    "present": True, "supported": True})
    return result


def minimal(**extra):
    tables = dict(
        workflow_base=[dict(id="w", workflowname="其他流程", formid="f", workflowtype="c")],
        workflow_bill=[dict(id="f", tablename="form_f")],
        workflow_billfield=[dict(id="10", billid="f", fieldname="name", fieldlabel="100",
                                 fieldhtmltype="1", type="1", fielddbtype="varchar(40)"),
                            dict(id="11", billid="f", fieldname="amount", fieldlabel="101",
                                 fieldhtmltype="1", type="3", fielddbtype="decimal(10,2)",
                                 detailtable="form_f_dt1", viewtype="1")],
        workflow_flownode=[dict(workflowid="w", nodeid="a", nodetype="0"),
                           dict(workflowid="w", nodeid="b", nodetype="1")],
        workflow_nodebase=[dict(id="a", nodename="开始"), dict(id="b", nodename="复核")],
        htmllabelinfo=[dict(indexid="100", languageid="7", labelname="姓名"),
                       dict(indexid="100", languageid="8", labelname="Name"),
                       dict(indexid="101", languageid="7", labelname="数量")],
    )
    tables.update(extra)
    return bundle(**tables)


class NormalizeTests(unittest.TestCase):
    def test_returns_one_workflow_from_one_base_record(self):
        self.assertEqual(len(normalize(minimal())), 1)

    def test_multi_workflows_forms_branch_and_cycle_are_scoped(self):
        data = minimal(workflow_nodelink=[
            dict(id="ab", workflowid="w", nodeid="a", destnodeid="b", condition="x > 1"),
            dict(id="ba", workflowid="w", nodeid="b", destnodeid="a", isreject="1"),
            dict(id="aa", workflowid="w", nodeid="a", destnodeid="a", condition="x <= 1")])
        other = bundle(workflow_base=[dict(id="w2", formid="f2", workflowname="独立")],
                       workflow_billfield=[dict(id="20", billid="f2", fieldname="flag")],
                       workflow_flownode=[dict(workflowid="w2", nodeid="c", nodetype="3")],
                       workflow_nodebase=[dict(id="c", nodename="归档")])
        for table, rows in other["tables"].items():
            data["tables"].setdefault(table, []).extend(rows)
        first, second = normalize(data)
        self.assertEqual([n["id"] for n in first["nodes"]], ["a", "b"])
        self.assertEqual(len(first["links"]), 3)
        self.assertEqual(first["links"][0]["condition"], "x > 1")
        self.assertTrue(first["links"][1]["is_reject"])
        self.assertEqual([f["id"] for f in second["fields"]], ["20"])
        self.assertEqual(second["nodes"][0]["type_name"], "归档")
        self.assertEqual(first["fields"][0]["label"], "姓名")
        self.assertEqual(normalize(data, language="8")[0]["fields"][0]["label"], "Name")
        self.assertTrue(first["fields"][1]["detail"])
        self.assertTrue(first["fields"][0]["source_refs"])

    def test_permission_missing_is_not_invisible_and_onlyshow_prohibits_edit(self):
        flow = normalize(minimal(workflow_nodeform=[
            dict(nodeid="a", fieldid="10", isview="1", isedit="1", ismandatory="1", isonlyshow="1"),
            dict(nodeid="a", fieldid="11", isview="0", isedit="1", ismandatory="0"),
            dict(nodeid="b", fieldid="10", isview="9", isedit=" ", ismandatory=" ")]))[0]
        perms = {(p["node_id"], p["field_id"]): p for p in flow["permissions"]}
        self.assertEqual(perms["b", "11"]["base_permission"], "missing")
        self.assertIsNone(perms["b", "11"]["view"])
        self.assertEqual(perms["a", "11"]["base_permission"], "invisible")
        self.assertTrue(perms["a", "10"]["manual_edit_prohibited"])
        self.assertEqual(perms["a", "10"]["base_permission"], "mandatory")
        self.assertIsNone(perms["b", "10"]["view"])
        self.assertTrue(any(i["code"] == "unknown_enum" for i in flow["issues"]))

    def test_active_layout_row_col_hidden_absent_and_mobile_are_separate(self):
        design = {"eformdesign": {"etables": {"emaintable": {
            "rowattrs": {"row_2": {"hide": "y"}},
            "colattrs": {"col_3": {"hide": "y"}},
            "ec": [{"id": "2,3", "field": "10", "etype": "3"}]}}}}
        layouts = [dict(id="pc", workflowid="w", nodeid="a", isactive="1", type="0",
                        datajson=json.dumps(design)),
                   dict(id="old", workflowid="w", nodeid="a", isactive="0", type="0", datajson="{}"),
                   dict(id="mobile", workflowid="w", nodeid="a", isactive="1", type="1", datajson="{}")]
        flow = normalize(minimal(workflow_nodehtmllayout=layouts))[0]
        placement = flow["layouts"][0]["placements"][0]
        self.assertEqual(placement["hidden"], ["row", "column"])
        p = next(p for p in flow["permissions"] if p["node_id"] == "a" and p["field_id"] == "11")
        self.assertEqual(len(p["layouts"]), 2)  # active views only
        self.assertEqual(p["layouts"][0]["placement"], "absent")
        self.assertEqual(p["layouts"][1]["placement"], "unknown")
        self.assertTrue(any(i["code"] == "layout_surface_ambiguity" for i in flow["issues"]))

    def test_operator_rules_resolve_joined_people_and_role_snapshot(self):
        flow = normalize(minimal(
            workflow_nodegroup=[dict(id="g", nodeid="a", groupname="审批")],
            workflow_groupdetail=[dict(id="r", groupid="g", type="2", objid="role", signorder="1"),
                                  dict(id="p", groupid="g", type="3", objid="", signorder="3"),
                                  dict(id="f", groupid="g", type="5", objid="10", signorder="1"),
                                  dict(id="c", groupid="g", type="17", objid="", signorder="1"),
                                  dict(id="u", groupid="g", type="987", objid="x", signorder="987")],
            workflow_hrmoperator=[dict(groupid="g", groupdetailid="p", objid="person", type="3", signorder="3")],
            hrmroles=[dict(id="role", rolesmark="测试角色")],
            hrmrolemembers=[dict(id="member", roleid="role", resourceid="person")]))[0]
        rules = {r["id"]: r for r in flow["operator_groups"][0]["rules"]}
        self.assertEqual(rules["r"]["kind"], "role")
        self.assertEqual(rules["r"]["objects"][0]["member_ids"], ["person"])
        self.assertEqual(rules["p"]["objects"][0]["id"], "person")
        self.assertEqual(rules["p"]["sign_type"], "抄送无需提交")
        self.assertEqual(rules["r"]["sign_type"], "会签")
        self.assertEqual(rules["f"]["kind"], "form_field")
        self.assertEqual(rules["c"]["kind"], "creator")
        self.assertEqual(rules["u"]["kind"], "unknown")
        self.assertFalse(rules["r"]["runtime_members_verified"])

    def test_stored_linkage_codes_are_not_runtime_codes(self):
        rows = [dict(workflowid="w", nodeid="a", selectfieldid="10_0", selectfieldvalue="0",
                     changefieldids="11_1", viewattr=code) for code in ("1", "2", "3", "4", "5", "97")]
        flow = normalize(minimal(workflow_viewattrlinkage=rows))[0]
        self.assertEqual([l["meaning"] for l in flow["linkages"]],
                         ["editable", "mandatory", "readonly", "hidden_content", "hidden_row", "unknown"])
        self.assertEqual([l["runtime_code"] for l in flow["linkages"]],
                         [2, 3, 1, None, None, None])
        self.assertEqual(flow["linkages"][-1]["raw"]["viewattr"], "97")

    def test_data_input_disabled_one_and_nested_mapping_and_sources(self):
        flow = normalize(minimal(
            workflow_datainput_entry=[dict(id="e0", workflowid="w", enable="0", triggername="来源", triggerfieldname="field10"),
                                      dict(id="e1", workflowid="w", enable="1"),
                                      dict(id="eb", workflowid="w", enable=" "),
                                      dict(id="eu", workflowid="w", enable="9")],
            workflow_datainput_main=[dict(id="m", entryid="e0", datasourcename="offline_ds", whereclause="id=?")],
            workflow_datainput_table=[dict(id="t", datainputid="m", tablename="source_table")],
            workflow_datainput_field=[dict(id="mf", datainputid="m", tableid="t", pagefieldname="field11", dbfieldname="quantity", type="2")]))[0]
        inputs = flow["data_inputs"]
        self.assertEqual([r["enabled"] for r in inputs], [True, False, True, None])
        self.assertEqual(inputs[0]["mappings"][0]["target_field"], "field11")
        self.assertEqual(inputs[0]["queries"][0]["tables"][0]["name"], "source_table")
        self.assertEqual(inputs[0]["trigger_field"], "field10")
        self.assertGreaterEqual(len(inputs[0]["source_refs"]), 4)

    def test_options_formula_details_actions_code_withdrawal_preserve_raw(self):
        flow = normalize(minimal(
            workflow_selectitem=[dict(id="o", fieldid="10", selectvalue="4", selectname="自定义", isdefault="y", cancel="0")],
            workflow_formula_htmllayout=[dict(formid="f", workflowid="w", nodeid="a", formula="[main.10]=[detail_1.11]", triggers="1#11")],
            workflow_nodeformgroup=[dict(nodeid="a", groupid="0", isadd="1", isedit="0", isdelete="0", iscopy="1", defaultrows="2")],
            workflow_addinoperate=[dict(id="act", workflowid="w", isnode="1", objid="b", type="3", customervalue="1")],
            workflow_code=[dict(formid="f", codefieldid="10", isuse="1")],
            workflow_coderegulate=[dict(formid="f", codevalue="ABC", codeorder="0")],
            workflow_codeseq=[dict(formid="f", sequenceid="9")],
            workflow_requestwithdraw=[dict(workflowid="w", allowwithdrawaltype="1", remarkrequired="1")]))[0]
        self.assertEqual(flow["options"][0]["value"], "4")
        self.assertTrue(flow["options"][0]["default"])
        self.assertEqual(flow["formulas"][0]["expression"], "[main.10]=[detail_1.11]")
        self.assertTrue(flow["detail_permissions"][0]["add"])
        self.assertFalse(flow["detail_permissions"][0]["edit"])
        self.assertTrue(flow["actions"][0]["external_action_marker"])
        self.assertIsNone(flow["actions"][0]["interface_id"])
        self.assertEqual(len(flow["code_rules"]), 3)
        self.assertEqual(flow["withdrawal"][0]["raw"]["remarkrequired"], "1")
        self.assertTrue(all(r["source_refs"] for key in ("options", "formulas", "detail_permissions", "actions", "code_rules", "withdrawal") for r in flow[key]))

    def test_dangling_references_and_absent_vs_exported_empty_and_no_mutation(self):
        data = minimal(workflow_nodelink=[dict(id="bad", workflowid="w", nodeid="a", destnodeid="ghost")],
                       workflow_selectitem=[],
                       workflow_nodeform=[dict(nodeid="a", fieldid="ghost", isview="1")])
        original = copy.deepcopy(data)
        flow = normalize(data)[0]
        self.assertEqual(data, original)
        self.assertEqual(flow["export_state"]["options"], "empty")
        self.assertEqual(flow["export_state"]["formulas"], "absent")
        self.assertTrue(any(i["code"] == "dangling_node_reference" for i in flow["issues"]))
        self.assertTrue(any(i["code"] == "dangling_field_reference" for i in flow["issues"]))

    def test_signature_required_operation_codes_do_not_mean_every_submit(self):
        data = minimal()
        data["tables"]["workflow_flownode"][0]["values"].update(
            issignmustinput="2", signmustinputtype="9,7")
        signature = normalize(data)[0]["nodes"][0]["signature"]
        self.assertEqual(signature["required_mode"], "2")
        self.assertEqual(signature["operation_types"], ["9", "7"])
        self.assertFalse(signature["runtime_verified"])

    def test_verified_node_and_sign_order_profile_and_unknown_boundary(self):
        data = minimal(workflow_nodegroup=[dict(id="g", nodeid="a")],
                       workflow_groupdetail=[dict(id=str(i), groupid="g", type="17", signorder=str(i))
                                             for i in range(6)])
        data["tables"]["workflow_flownode"] = [
            {"values": dict(workflowid="w", nodeid=f"n{i}", nodetype=str(i)),
             "ref": f"node{i}"} for i in range(8)]
        data["tables"]["workflow_nodebase"] = [
            {"values": dict(id=f"n{i}", nodename=f"节点{i}"), "ref": f"base{i}"} for i in range(8)]
        data["tables"]["workflow_nodegroup"][0]["values"]["nodeid"] = "n0"
        flow = normalize(data)[0]
        self.assertEqual([n["type_name"] for n in flow["nodes"]],
                         ["创建", "审批", "提交", "归档", "传阅", "等待", "自动处理", "未知"])
        self.assertEqual([r["sign_type"] for r in flow["operator_groups"][0]["rules"]],
                         ["非会签", "会签", "依次逐个", "抄送无需提交", "抄送需提交", "未知"])
        unknowns = [i["message"] for i in flow["issues"] if i["code"] == "unknown_enum"]
        self.assertEqual(len(unknowns), 2)

    def test_layout_decorations_are_not_fields_and_disabled_layouts_are_preserved(self):
        design = {"eformdesign": {"etables": {"emaintable": {"ec": [
            {"id": "0,0", "field": "10", "etype": "29", "evalue": "装饰"},
            {"id": "1,0", "field": "11", "etype": "3"}]}}}}
        flow = normalize(minimal(workflow_nodehtmllayout=[dict(
            id="disabled", nodeid="a", workflowid="w", type="0", isactive="0",
            datajson=json.dumps(design))]))[0]
        self.assertFalse(flow["layouts"][0]["active"])
        self.assertEqual([p["field_id"] for p in flow["layouts"][0]["placements"]], ["11"])
        self.assertTrue(all(not p["layouts"] for p in flow["permissions"]))

    def test_data_input_parent_refs_are_supported_without_foreign_keys(self):
        data = minimal(workflow_datainput_entry=[dict(id="entry", workflowid="w")],
                       workflow_datainput_main=[dict(id="main")],
                       workflow_datainput_table=[dict(id="table", tablename="offline")],
                       workflow_datainput_field=[dict(id="field", pagefieldname="field10")])
        tables = data["tables"]
        entry = tables["workflow_datainput_entry"][0]
        main = tables["workflow_datainput_main"][0]
        table = tables["workflow_datainput_table"][0]
        mapping = tables["workflow_datainput_field"][0]
        main["parent_ref"], table["parent_ref"], mapping["parent_ref"] = entry["ref"], main["ref"], table["ref"]
        item = normalize(data)[0]["data_inputs"][0]
        self.assertEqual(item["mappings"][0]["target_field"], "field10")
        self.assertEqual(item["queries"][0]["tables"][0]["name"], "offline")
        self.assertEqual(len(item["source_refs"]), 4)

    def test_unknown_layout_shape_is_an_issue_instead_of_a_crash(self):
        for design in ({"eformdesign": []}, {"eformdesign": {"etables": {"main": {"ec": []}}}}):
            with self.subTest(design=design):
                flow = normalize(minimal(workflow_nodehtmllayout=[dict(
                    id="layout", workflowid="w", nodeid="a", isactive="1", datajson=json.dumps(design))]))[0]
                self.assertEqual(len(flow["layouts"]), 1)
        self.assertEqual(normalize(minimal(workflow_nodehtmllayout=[dict(
            id="layout", workflowid="w", nodeid="a", isactive="1",
            datajson='{"eformdesign":[]}')]))[0]["layouts"][0]["parse_status"], "unsupported")

    def test_dangling_references_in_rules_and_explicit_layout_scope_are_evidenced(self):
        flow = normalize(minimal(
            workflow_selectitem=[dict(id="option", workflowid="w", fieldid="ghost")],
            workflow_viewattrlinkage=[dict(workflowid="w", nodeid="a", selectfieldid="10_0",
                                          changefieldids="ghost_1", viewattr="3")],
            workflow_nodehtmllayout=[dict(id="layout", workflowid="w", nodeid="missing", isactive="0")]))[0]
        messages = [i["message"] for i in flow["issues"] if i["code"].startswith("dangling_")]
        self.assertTrue(any("ghost" in x for x in messages))
        self.assertTrue(any("missing" in x for x in messages))


if __name__ == "__main__":
    unittest.main()
