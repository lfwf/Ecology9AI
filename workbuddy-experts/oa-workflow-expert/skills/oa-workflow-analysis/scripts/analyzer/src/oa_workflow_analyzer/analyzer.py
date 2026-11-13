"""Combine configuration facts, inert script clues, and actionable evidence gaps."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import __version__
from .archive import load_export, ParseError
from .normalize import PROFILE, normalize
from .scripts import analyze_script, decode_layout_text, sanitize_script

SCHEMA_VERSION = "1.0"


def _safe(value):
    if isinstance(value, str):
        return sanitize_script(value)
    if isinstance(value, list):
        return [_safe(x) for x in value]
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if re.fullmatch(r"(?i)(password|passwd|pwd|access[_-]?token|refresh[_-]?token|token|secret|client[_-]?secret|api[_-]?key|authorization|cookie|private[_-]?key|session[_-]?id)", str(k)) else _safe(v)) for k, v in value.items()}
    return value


class _Gaps:
    def __init__(self):
        self.items, self.keys = [], set()

    def add(self, code, scope, title, reason, needed, how, refs=(), *, category="missing", severity="warning"):
        refs = sorted(set(refs))
        key = (code, scope, reason, tuple(refs))
        if key in self.keys:
            return
        self.keys.add(key)
        self.items.append({"id": f"gap{len(self.items) + 1:04}", "code": code, "category": category,
                           "severity": severity, "scope": scope or "export", "title": title,
                           "reason": reason, "needed": needed, "how_to_collect": how,
                           "source_refs": refs})


def _table_state(bundle, name):
    name = name.casefold()
    if name not in bundle["tables"]:
        return "未随文件导出"
    return "已导出为空" if not bundle["tables"][name] else "已包含配置记录"


def _collect_scripts(bundle, gaps):
    scripts = []
    for record in bundle["tables"].get("workflow_nodehtmllayout", []):
        value = record["values"]
        seen = {}
        for channel in ("scriptstr", "scripts", "initscripts"):
            if not value.get(channel, "").strip():
                continue
            decoding = decode_layout_text(value[channel])
            text = decoding.get("text", "")
            # Treat newline-only differences between legacy duplicate channels
            # as the same source, while preserving one original line sequence.
            key = text.replace("\r\n", "\n").replace("\r", "\n").strip() if decoding["status"] != "unsupported" else value[channel]
            if key in seen:
                seen[key]["channels"].append(channel)
                continue
            safe_text = sanitize_script(text)
            active_value = value.get("isactive", "").strip().casefold()
            active = True if active_value in {"1", "y", "yes", "true"} else False if active_value in {"0", "n", "no", "false"} else None
            item = {"id": f"script{len(scripts) + 1:04}", "node_id": value.get("nodeid", ""),
                    "workflow_id": value.get("workflowid", ""), "layout_id": value.get("id", ""),
                    "active": active, "channels": [channel],
                    "source_refs": [record["ref"]], "decoding": {k: v for k, v in decoding.items() if k != "text"},
                    "text": safe_text, "sanitized_text_sha256": hashlib.sha256(safe_text.encode("utf-8")).hexdigest(),
                    "analysis": analyze_script(safe_text)}
            scripts.append(item)
            seen[key] = item
            scope = f"workflow:{item['workflow_id']}/node:{item['node_id']}/layout:{item['layout_id']}"
            if decoding["status"] == "unsupported":
                gaps.add("LAYOUT_SCRIPT_DECODE", scope, "布局脚本尚未解码", decoding.get("error", "布局编码不属于已支持配置档案"),
                         "对应 OA 版本的布局脚本编码方式或明文导出", "只读导出该布局的脚本，核对平台版本及编码实现", item["source_refs"], category="unsupported")
            if item["active"] is False:
                continue
            if item["active"] is None:
                gaps.add("LAYOUT_ACTIVITY_UNKNOWN", scope, "布局生效状态不明确", f"isactive={active_value!r} 不能解释成已停用或已启用",
                         "该布局在当前节点和设备上是否生效", "只读核对节点活动模板；此处接口引用作为可能依赖保留", item["source_refs"], category="unsupported")
            for call in item["analysis"]["network_calls"]:
                if call.get("url"):
                    url = call["url"]
                    gaps.add("EXTERNAL_ENDPOINT_IMPLEMENTATION", scope, "接口实现不在流程导出内",
                             f"脚本静态引用 {url}；地址存在不证明部署或业务执行结果", f"{url} 对应接口源码、部署类及参数响应约定",
                             "只读取得接口实现和当前加载版本；不要为解析流程调用写接口", item["source_refs"])
            for warning in item["analysis"]["warnings"]:
                message = warning.get("message", str(warning)) if isinstance(warning, dict) else str(warning)
                code = warning.get("code", "STATIC_SCRIPT_LIMIT") if isinstance(warning, dict) else "STATIC_SCRIPT_LIMIT"
                gaps.add("SCRIPT_" + code.upper(), scope, "脚本静态分析边界", message,
                         "相关脚本分支、动态构造的值或执行顺序证据", "按脚本行号只读检查代码及运行日志，区分静态线索和执行事实",
                         item["source_refs"], category="unsupported")
    return scripts


def _dependencies(bundle, workflows, scripts, gaps):
    tables = bundle["tables"]
    values_by_ref = {r["ref"]: r["values"] for rows in tables.values() for r in rows}
    for flow in workflows:
        scope, refs = f"workflow:{flow['id']}", flow.get("source_refs", [])
        gaps.add("RUNTIME_VERSION", scope, "线上生效版本尚未验证", "导出配置和本地解析不能证明当前服务器加载版本",
                 "生效流程版本、OA 版本、服务器部署类与配置的校验记录", "只读核对流程版本和实际 class/JAR 加载路径及哈希", refs, category="runtime", severity="info")
        gaps.add("BUSINESS_INSTANCE_DATA", scope, "业务运行数据未包含在定义中", "流程定义不包含每张申请的实际取人、审批日志或外部系统执行结果",
                 "具体 requestid、流程日志、人员取人结果、接口回执和相关业务单据", "选取有授权的历史请求，只读导出运行日志及外部系统回执", refs, category="runtime", severity="info")
        for issue in flow.get("issues", []):
            code = str(issue.get("code", "UNKNOWN_CONFIGURATION")).upper()
            issue_refs = issue.get("source_refs", refs)
            context = [{k: v for k, v in values_by_ref.get(ref, {}).items()
                        if k in {"id", "nodeid", "destnodeid", "fieldid", "selectfieldid", "changefieldids", "objid", "groupid"}}
                       for ref in issue_refs]
            reason = issue.get("message", str(issue))
            if any(context):
                reason += "；引用内容：" + json.dumps(context, ensure_ascii=False, sort_keys=True)
            gaps.add(code, scope, "配置需要补充核对", reason,
                     "该配置的完整引用、对应版本规则或缺失记录", "按证据引用定位原始导出，补充定义或核对当前平台实现",
                     issue_refs, category="unsupported")
        for field in flow.get("fields", []):
            db_type = field.get("db_type", "")
            if db_type.casefold().startswith("browser."):
                browser = db_type.split(".", 1)[1]
                definitions = tables.get("workflow_browdef", [])
                found = any(browser == r["values"].get(key) for r in definitions for key in ("id", "browserid", "browsermark"))
                if not found:
                    gaps.add("BROWSER_DEFINITION", scope + "/field:" + field["id"], "自定义浏览定义缺失",
                             f"字段引用 {db_type}；workflow_browdef {_table_state(bundle, 'workflow_browdef')}",
                             f"{db_type} 的查询 SQL、数据源、返回字段与权限范围", "只读导出对应自定义浏览配置，不将浏览器标识当作实际查询规则", field.get("source_refs", []))
        for action in flow.get("actions", []):
            raw = action.get("raw", {})
            if str(raw.get("type", "")) != "3":
                continue
            node = raw.get("objid", action.get("node_id", ""))
            is_node = raw.get("isnode", "1") == "1"
            location_key = "nodeid" if is_node else "nodelinkid"
            phase = raw.get("ispreadd", "")
            candidates = [r for name in ("workflowactionset", "workflowactionview", "sapactionset") for r in tables.get(name, [])
                          if r["values"].get("workflowid") == flow["id"] and r["values"].get(location_key) == node
                          and r["values"].get("isused", "").strip().casefold() in {"1", "y", "yes", "true"}
                          and phase in {"0", "1"} and r["values"].get("ispreoperator") == phase
                          and any(r["values"].get(key, "").strip() for key in ("interfaceid", "actionname", "classname", "actionclass"))]
            if not candidates:
                states = "; ".join(f"{name} {_table_state(bundle, name)}" for name in ("workflowactionset", "workflowactionview", "sapactionset"))
                gaps.add("EXTERNAL_ACTION_DEFINITION", scope + "/node:" + str(node), "节点接口操作定义缺失",
                         "仅有 type=3 的集成操作标记，customervalue 不是接口主键；" + states,
                         "workflowactionset/workflowactionview/sapactionset 中对应节点、前后时机及 isused 的实际注册项、类名和参数",
                         "只读导出该节点的接口前后操作及注册实现，核对时机后再关联源码", action.get("source_refs", []))
            else:
                gaps.add("EXTERNAL_ACTION_IMPLEMENTATION", scope + "/" + location_key + ":" + str(node), "接口注册存在但实现仍需核对",
                         "包中有匹配启用状态及执行时机的注册记录；定义不能证明对应类、服务实现或当前部署",
                         "接口注册指向的类、服务实现、参数约定及部署版本",
                         "按注册项 interfaceid/actionname 只读取得实现和加载版本", [r["ref"] for r in candidates])
        if any(rule.get("kind") == "role" for group in flow.get("operator_groups", []) for rule in group.get("rules", [])):
            gaps.add("CURRENT_ROLE_MEMBERS", scope, "角色成员仅为导出快照", "角色规则和可选成员快照不能证明当前在职权限",
                     "运行时角色成员、角色范围和人员状态", "只读核对 OA 组织权限与本次请求取人日志", refs, category="runtime", severity="info")
    for record in tables.get("workflow_datainput_table", []):
        name = record["values"].get("tablename", "")
        if name:
            gaps.add("EXTERNAL_DATA_SOURCE", "data-input:" + record["values"].get("datainputid", ""), "带入规则的数据内容在包外",
                     f"配置引用数据表 {name}，定义不包含其完整查询数据或当前可用性；禁用规则也保留依赖记录",
                     f"{name} 的结构、必要匹配字段与数据源配置；并核对对应规则启用状态",
                     "只读取得规则数据源定义及去敏样例，不执行更新语句", [record["ref"]])
    for record in tables.get("workflow_datainput_main", []):
        name = record["values"].get("datasourcename", "").strip()
        if name:
            gaps.add("NAMED_DATA_SOURCE", "data-input:" + record["values"].get("entryid", ""), "命名数据源定义在包外",
                     f"配置引用命名数据源 {name}，流程定义不包含连接配置和运行可用性",
                     f"{name} 的数据源类型、查询结构及启用状态；连接凭据不应写入分析报告",
                     "只读导出不含密码的数据源定义，并按相应带入规则核对关联和启用状态", [record["ref"]])
    entry_names = {x["name"].replace("\\", "/").lstrip("/").casefold() for x in bundle["source"]["archive_entries"]}
    for table, records in tables.items():
        for record in records:
            meta = {k.casefold(): v for k, v in record["meta"].items()}
            columns = re.split(r"[,，]", meta.get("filepathcolumn", ""))
            for column in columns:
                value = record["values"].get(column.strip().casefold(), "").strip()
                if value and value.replace("\\", "/").lstrip("/").casefold() not in entry_names:
                    gaps.add("EXTERNAL_FILE", table + "/" + record["ref"], "引用文件未随导出提供", f"文件列 {column} 引用 {value}，包中无对应条目",
                             "对应布局、模板或附件文件及其哈希", "只读复制引用文件，保留相对路径和版本校验", [record["ref"]])


def analyze_export(path, *, language="7"):
    """Analyze any supported export; runtime behavior is never asserted verified."""
    bundle = load_export(Path(path))
    workflows = normalize(bundle, language=str(language))
    if not workflows:
        raise ParseError("WORKFLOW_BASE_MISSING", "没有可定位的流程基本定义，不能生成空的成功说明书")
    gaps = _Gaps()
    for issue in bundle["issues"]:
        gaps.add(issue["code"], "export", "输入字段需要核对", issue["message"], "可解码的原始字段与平台编码约定",
                 "按 XML 行号和表字段核对导出值与平台版本", issue.get("source_refs", []), category="unsupported")
    for item in bundle["inventory"]:
        if item["count"] and not item["supported"] and not item.get("excluded"):
            gaps.add("UNSUPPORTED_CONFIGURATION", "table:" + item["table"], "配置保留但语义尚未解释",
                     f"{item['table']} 有 {item['count']} 条记录，当前版本仅保留原始证据和表清单",
                     "该表对应平台版本的字段定义及业务规则", "只读查看相关后台配置或源码，增加独立解析适配器并回归测试",
                     [r["ref"] for r in bundle["tables"].get(item["table"], [])], category="unsupported")
    scripts = _collect_scripts(bundle, gaps)
    _dependencies(bundle, workflows, scripts, gaps)
    evidence = [{"id": record["ref"], "table": table, "line": record["line"], "element_id": record["element_id"],
                 "parent_ref": record["parent_ref"], "values": _safe(record["values"]),
                 "metadata": record["meta"], "decodings": record["decodings"]}
                for table, records in bundle["tables"].items() for record in records]
    summary = {"workflow_count": len(workflows), "node_count": sum(len(x["nodes"]) for x in workflows),
               "link_count": sum(len(x["links"]) for x in workflows), "field_count": sum(len(x["fields"]) for x in workflows),
               "gap_count": len(gaps.items), "script_count": len(scripts),
               "status": "partial" if any(g["category"] == "unsupported" for g in gaps.items) else "parsed"}
    return _safe({"schema_version": SCHEMA_VERSION, "analyzer": {"name": "oa-workflow-analyzer", "version": __version__,
             "profile": PROFILE, "language": str(language), "runtime_verified": False,
             "profile_scope": "Locally verified E9 meanings; unknown versions and values require evidence"},
            "source": bundle["source"], "workflows": _safe(workflows), "table_inventory": deepcopy(bundle["inventory"]),
            "evidence": evidence, "scripts": scripts, "gaps": _safe(gaps.items), "summary": summary})
