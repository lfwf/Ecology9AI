# Implementation contract version 1

All paths relative to this package. Package is `src/oa_workflow_analyzer`. Root owns archive.py, analyzer.py, CLI, schema and integration. Other agents own disjoint modules specified in their tasks. Do not edit other agents' files or commit shared changes.

## Archive bundle supplied to normalize and analyzer

`load_export(path) -> dict` returns source metadata, tables, inventory, issues, attachments. Tables keys are lower case; values are lists of records. A record is `{"values": {"lowercase_field": "string"}, "meta": {...original TABLE attributes...}, "ref": "ev000001", "line": 123}`. Empty/missing values are strings. UUID rewrite records and sensitive personnel/license fields are excluded; table presence and counts remain in inventory. `source` has name, sha256, size_bytes, xml_sha256, encoding and archive_entries. Issues use code, message, source_refs. Inventory items have element_id, table, count, supported and present.

## Normalizer

`normalize(bundle, *, language='7') -> list[dict]`. Each workflow has id, name, form_id, category, nodes, links, fields, permissions, detail_permissions, operator_groups, options, formulas, linkages, data_inputs, actions, layouts, code_rules, withdrawal, source_refs, issues. Additional factual sections allowed. IDs are strings. Unknown data stays raw. Each normalized record carries source_refs list; include original values under `raw` when needed. Fields include id, name, label, table, db_type, html_type, browser_type, detail (bool). Nodes include id,name,type,type_name and source_refs. Links include id,from_node,to_node,name,condition (raw text),is_reject,source_refs. Permissions include node_id,field_id,view,edit,mandatory,manual_edit_prohibited,base_permission,layouts list and source_refs. Layouts keep id,node_id,active,name,placements; placements identify field_id,table,cell,hidden flags. Preserve parsed layout data for root script extraction via original bundle records, no need repeat large datajson. Data inputs include id,name,enabled,trigger_field,mappings,source refs and raw. Actions raw are evidence, type3/customervalue1 is marker, not interface id.

## Script module

`decode_layout_text(value: str) -> dict` returns text, status (`plain`/`decoded`/`empty`/`unsupported`), encoding, error optional. Recognized E-Design uses local profile, never execute text. `analyze_script(text: str) -> dict` returns events, functions, network_calls, field_writes, attribute_changes, conditions, warnings. Findings have line and snippet or literal text. Events include operation, line, calls, reachable_endpoints; network_calls include url,line and source function if known. Ignore commented-out code. Follow simple named local functions conservatively; unknown dynamic behavior is a warning, not inferred success. `sanitize_script(text) -> str` masks obvious credential assignments/Authorization values without running code. Preserve line numbers.

## Combined public result owned by root

`analyze_export(path, *, language='7') -> dict`: schema_version, analyzer, source, workflows, table_inventory, evidence, scripts, gaps, summary. Scripts include id,node_id,layout_id,active,source_refs,decoding,text (sanitized),analysis. A gap has id,code,category,severity,scope,title,reason,needed,how_to_collect,source_refs. Distinguish missing, unsupported and runtime evidence. Summary contains workflow_count,node_count,link_count,field_count,gap_count,script_count and status (`parsed`/`partial`, never live verification).

## Report module

`render_markdown(result) -> str`, `render_html(result) -> str`, `render_pdf(result, path) -> None` optional dependency. `write_analysis` orchestration owned by root uses these. Render variable numbers of workflows, nodes, fields and permissions, operators, selected enums, formula/linkage/data-input/action facts, static script events/endpoints and gaps. Reports must not guess calculations from field names. HTML escape all source text, no remote resources or executing source snippets. Output contains source fingerprint and profile, explicit offline-only scope, links to structured companion files. A stable source/hash based graph rendering or Mermaid for MD, readable node+edge view in HTML/PDF is sufficient; do not hard-code current flow.

## Test commands

Use bundled Python `./examples/user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`, with PYTHONPATH pointing at this package's src and PYTHONIOENCODING=utf-8. Tests use unittest. Synthetic bundle test helpers can be local to the owning test module. No source .wewf or personal data committed. Optional integration test reads `OA_WORKFLOW_SAMPLE` env path only, without requiring it for normal tests.
