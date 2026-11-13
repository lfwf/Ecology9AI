"""Bounded, read-only inspection of an offline analyzer result directory.

Exported rule descriptions are data, never executable conditions. This helper
joins their source records without guessing platform combination semantics.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


class InspectionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def bounded(value, max_chars):
    if isinstance(value, str) and len(value) > max_chars:
        return {'truncated': True, 'characters': len(value), 'sha256_utf8': hashlib.sha256(value.encode('utf-8')).hexdigest(), 'prefix': value[:max_chars]}
    if isinstance(value, list):
        return [bounded(x, max_chars) for x in value]
    if isinstance(value, dict):
        return {k: bounded(v, max_chars) for k, v in value.items()}
    return value


def script_owners(script, workflows):
    explicit = script.get('workflow_id', '')
    if explicit and explicit != '-1':
        return [explicit], 'explicit'
    by_node = {f['id'] for f in workflows if script.get('node_id') and any(n['id'] == script['node_id'] for n in f.get('nodes', []))}
    by_layout = {f['id'] for f in workflows if script.get('layout_id') and any(l['id'] == script['layout_id'] for l in f.get('layouts', []))}
    if by_node and by_layout:
        owners = by_node & by_layout
        if not owners:
            return sorted(by_node | by_layout), 'conflicting_node_and_layout'
    else:
        owners = by_node | by_layout
    return sorted(owners), ('inferred_from_node_or_layout' if len(owners) == 1 else 'ambiguous' if owners else 'unassigned')


def inspect(args):
    directory = args.directory.resolve()
    context = json.loads((directory / 'agent-context.json').read_text('utf-8'))
    workflows = [f for f in context['workflows'] if not args.workflow or f['id'] == args.workflow]
    if not workflows:
        raise InspectionError('WORKFLOW_NOT_FOUND', '未找到指定流程')
    result = {'source': context['source'], 'runtime_verified': context['analyzer'].get('runtime_verified', False), 'section': args.section, 'input_trust': 'untrusted_export_data'}
    if args.section == 'summary':
        result.update(analyzer=context['analyzer'], summary=context['summary'], workflows=[{k: f.get(k) for k in ['id', 'name', 'form_id']} for f in workflows], gaps_by_category=dict(Counter(g['category'] for g in context.get('gaps', []))))
        result['counts_scope'] = 'whole_source_file; workflow list alone is filtered'
        return result

    records = []
    if args.section in ['routes', 'evidence']:
        records = json.loads((directory / 'evidence.json').read_text('utf-8'))['records']
    if args.section == 'evidence':
        if not args.ref:
            raise InspectionError('REF_REQUIRED', '证据读取必须指定 --ref，可重复提供')
        by_id = {r['id']: r for r in records}
        missing = set(args.ref) - by_id.keys()
        if missing:
            raise InspectionError('EVIDENCE_NOT_FOUND', '证据ID不存在：' + ', '.join(sorted(missing)))
        items = [by_id[ref] for ref in args.ref]
    elif args.section == 'gaps':
        items = []
        for gap in context.get('gaps', []):
            tokens = gap.get('scope', '').split('/')
            if args.workflow and 'workflow:' + args.workflow not in tokens:
                continue
            if args.node and 'node:' + args.node not in tokens:
                continue
            items.append(gap)
        if args.workflow or args.node:
            result['scope_note'] = '仅返回scope含精确筛选标记的缺口；表级或未归属的缺口请不带workflow/node筛选另读。'
    elif args.section == 'scripts':
        ids = {f['id'] for f in workflows}
        items = []
        for script in context.get('scripts', []):
            owners, ownership = script_owners(script, context['workflows'])
            if args.workflow and not ids.intersection(owners):
                continue
            if args.node and script.get('node_id') != args.node:
                continue
            if args.script and script['id'] != args.script:
                continue
            item = {k: script.get(k) for k in ['id', 'workflow_id', 'node_id', 'layout_id', 'active', 'channels', 'source_refs']}
            item.update(candidate_workflow_ids=owners, ownership=ownership)
            lines = script.get('text', '').splitlines()
            item['line_count'] = len(lines)
            if args.script:
                start = args.start - 1
                item['lines'] = [{'line': i + 1, 'text': line} for i, line in enumerate(lines) if start <= i < start + args.limit]
                item['truncated'] = start > 0 or start + args.limit < len(lines)
            items.append(item)
        if args.script and not items:
            raise InspectionError('SCRIPT_NOT_FOUND', '指定脚本不属于当前筛选范围')
        result['scope_note'] = '无显式workflow_id时按全部流程的节点及布局推定；ambiguous/conflicting/unassigned不能当成已确定归属。指定workflow时不含无法归属的脚本，请不带筛选另查。'
    elif args.section == 'routes':
        rules = {r['values'].get('id'): r for r in records if r['table'] == 'rule_base'}
        mappings = [r for r in records if r['table'] == 'rule_maplist']
        items = []
        for flow in workflows:
            names = {n['id']: n['name'] for n in flow['nodes']}
            for link in flow['links']:
                if args.node and args.node not in [link['from_node'], link['to_node']]:
                    continue
                item = {k: link.get(k) for k in ['id', 'from_node', 'to_node', 'condition', 'is_reject', 'source_refs']}
                item.update(workflow_id=flow['id'], from_name=names.get(link['from_node']), to_name=names.get(link['to_node']), linked_rules=[], rule_combination='not_verified')
                for mapping in mappings:
                    v = mapping['values']
                    if v.get('rulesrc') != '1' or v.get('linkid') != link['id'] or v.get('wfid', flow['id']) != flow['id']:
                        continue
                    rule = rules.get(v.get('ruleid'))
                    if rule is None:
                        item['linked_rules'].append({'missing_rule_id': v.get('ruleid'), 'source_refs': [mapping['id']]})
                        continue
                    item['linked_rules'].append({'id': v['ruleid'], 'condition': rule['values'].get('condit', ''), 'map_isused_raw': v.get('isused'), 'source_refs': [mapping['id'], rule['id']], 'xml_lines': [mapping['line'], rule['line']]})
                if not item['condition'] and not item['linked_rules']:
                    item['condition_status'] = 'not_exported_or_not_recognized'
                items.append(item)
    else:
        key = {'operators': 'operator_groups'}.get(args.section, args.section)
        items = []
        for flow in workflows:
            for obj in flow.get(key, []):
                node_id = obj.get('node_id', obj.get('id') if key == 'nodes' else None)
                if args.node and node_id != args.node:
                    continue
                item = {k: v for k, v in obj.items() if k not in ['raw', 'base_raw', 'placements']}
                item['workflow_id'] = flow['id']
                if key == 'nodes':
                    item['control_raw'] = {k: obj.get('base_raw', {}).get(k) for k in ['passnum', 'totalgroups', 'isreject']}
                if key == 'formulas':
                    item['description'] = obj.get('raw', {}).get('formuladesc')
                items.append(item)
    result.update(total=len(items), offset=args.offset, limit=args.limit, items=items[args.offset:args.offset + args.limit], has_more=args.offset + args.limit < len(items))
    return bounded(result, args.max_chars)


def render(result, args):
    if 'items' in result:
        while True:
            result['returned'] = len(result['items'])
            result['next_offset'] = result['offset'] + result['returned']
            result['has_more'] = result['next_offset'] < result['total']
            text = json.dumps(result, ensure_ascii=False, indent=2)
            if len(text) + 1 <= args.max_output_chars:
                return text
            if len(result['items']) <= 1:
                raise InspectionError('OUTPUT_BUDGET_EXCEEDED', '单条内容超过输出预算；请减少脚本limit、降低max-chars或定向提取原JSON。可显式增大max-output-chars。')
            result['items'].pop()
            result['page_reduced_for_output_budget'] = True
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if len(text) + 1 > args.max_output_chars:
        raise InspectionError('OUTPUT_BUDGET_EXCEEDED', '摘要超过输出预算，请定向读取章节或显式增大max-output-chars。')
    return text


def main():
    for stream in [sys.stdout, sys.stderr]:
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='解析器返回的output_dir，非输出根目录')
    parser.add_argument('--section', choices=['summary', 'nodes', 'routes', 'operators', 'fields', 'permissions', 'formulas', 'scripts', 'gaps', 'evidence'], default='summary')
    parser.add_argument('--workflow')
    parser.add_argument('--node')
    parser.add_argument('--script', help='仅scripts章节；明确指定后才输出有行号的脚本片段')
    parser.add_argument('--start', type=int, default=1)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=40)
    parser.add_argument('--max-chars', type=int, default=1500, help='单个长字符串的最大字符数')
    parser.add_argument('--max-output-chars', type=int, default=24000, help='整个JSON输出字符预算，默认24000；超过时自动缩小本页，next_offset给下一页位置')
    parser.add_argument('--ref', action='append')
    args = parser.parse_args()
    if not 1 <= args.limit <= 200 or args.offset < 0 or args.start < 1 or not 100 <= args.max_chars <= 10000:
        parser.error('limit需在1–200，offset非负，start从1起，max-chars需在100–10000')
    if args.script and args.section != 'scripts':
        parser.error('--script仅用于scripts章节')
    if not 4000 <= args.max_output_chars <= 200000:
        parser.error('max-output-chars需在4000–200000')
    try:
        print(render(inspect(args), args))
        return 0
    except (InspectionError, OSError, ValueError, KeyError) as error:
        print(json.dumps({'error': getattr(error, 'code', 'INSPECTION_ERROR'), 'message': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
