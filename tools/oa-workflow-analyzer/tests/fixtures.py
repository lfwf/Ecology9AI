"""Small independent exports; IDs and topology differ from the real sample."""
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
import zipfile


def export_bytes(*, script="", active="1", extra=None):
    tables = {
        "workflow_base": [{"id": "900", "workflowname": "测试采购以外的流程", "formid": "-80"}],
        "workflow_bill": [{"id": "-80", "tablename": "form_80"}],
        "workflow_billfield": [{"id": "7", "billid": "-80", "fieldname": "amount", "fieldlabel": "30", "fielddbtype": "int", "fieldhtmltype": "1"}],
        "htmllabelinfo": [{"indexid": "30", "languageid": "7", "labelname": "数量"}],
        "workflow_flownode": [{"workflowid": "900", "nodeid": "10", "nodetype": "0"}, {"workflowid": "900", "nodeid": "20", "nodetype": "3"}],
        "workflow_nodebase": [{"id": "10", "nodename": "发起", "isstart": "1"}, {"id": "20", "nodename": "结束", "isend": "1"}],
        "workflow_nodelink": [{"id": "L", "workflowid": "900", "nodeid": "10", "destnodeid": "20", "condition": "amount > 0"}],
        "workflow_nodeform": [{"nodeid": "10", "fieldid": "7", "isview": "1", "isedit": "1", "ismandatory": "1"}, {"nodeid": "20", "fieldid": "7", "isview": "1", "isedit": "0"}],
    }
    if script:
        tables["workflow_nodehtmllayout"] = [{"id": "55", "workflowid": "900", "nodeid": "10", "isactive": active, "scriptstr": script, "scripts": script, "datajson": "{}"}]
    tables.update(extra or {})
    root = Element("root")
    for name, rows in tables.items():
        element = SubElement(root, "ELEMENT", ID=name, TABLENAME=name)
        for row in rows:
            table = SubElement(element, "TABLE", ID=name, TABLENAME=name)
            for key, value in row.items():
                field = SubElement(table, "FIELD", FIELDNAME=key)
                if key in {"scriptstr", "scripts", "datajson"}:
                    field.set("FIELDTEXT", "y")
                    field.text = value
                else:
                    field.set("FIELDVALUE", value)
    return tostring(root, encoding="utf-8", xml_declaration=True)


def write_export(directory, name="另一个流程.wewf", **kwargs):
    target = Path(directory) / name
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("workflow.xml", export_bytes(**kwargs))
    return target
