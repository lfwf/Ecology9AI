"""B01 deterministic normalization, immutable batches and review records (stdlib only)."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(__file__).resolve().parent
METHOD = json.loads((HOME / 'registry' / 'B01.json').read_text(encoding='utf-8'))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def capture_time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('Capture time must include timezone')
    return parsed


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def normalize(raw):
    if raw.get('category') != 'B01' or raw.get('format_version') != 1:
        raise ValueError('Unsupported B01 capture format')
    if not raw.get('schema') or not raw.get('source_identity') or not raw.get('method_version'):
        raise ValueError('Missing source/schema/method evidence')
    if capture_time(raw['ended_at']) < capture_time(raw['started_at']):
        raise ValueError('Capture ended before it started')
    tables = raw.get('tables', {})
    indexes = {}
    for table, fields in METHOD['tables'].items():
        rows = tables.get(table)
        check = raw.get('checks', {}).get(table, {})
        if not isinstance(rows, list) or not check.get('complete'):
            raise ValueError(f'Incomplete configuration source: {table}')
        if check.get('row_count') != len(rows) or len(rows) > METHOD['limits']['max_rows_per_table']:
            raise ValueError(f'Row count mismatch/cap: {table}')
        if not check.get('hash_first') or check['hash_first'] != check.get('hash_second'):
            raise ValueError(f'Configuration changed during capture: {table}')
        index = {}
        for row in rows:
            if set(fields) - set(row) or type(row['id']) is not int or row['id'] in index:
                raise ValueError(f'Missing fields or duplicate/invalid source key: {table}')
            index[row['id']] = row
        indexes[table] = index
    if not indexes['workflow_base']:
        raise ValueError('Empty workflow directory requires investigation; previous success preserved')

    workflows, issues = [], []
    shared, names = defaultdict(list), defaultdict(list)
    def issue(kind, workflow_id):
        issues.append(dict(kind=kind, workflow_id=workflow_id))
    for source in sorted(tables['workflow_base'], key=lambda x: x['id']):
        wid = source['id']
        selector = source['isbill']  # Deliberately no trimming/coercion of source codes.
        table = {'1': 'workflow_bill', '0': 'workflow_formbase'}.get(selector)
        form = indexes[table].get(source['formid']) if table else None
        category = indexes['workflow_type'].get(source['workflowtype'])
        if not category: issue('missing_category', wid)
        if not table: issue('unknown_form_selector', wid)
        elif not form: issue('missing_form', wid)
        if source['activeVersionID'] is not None and source['activeVersionID'] not in indexes['workflow_base']:
            issue('missing_active_version', wid)
        if not (source['workflowname'] or '').strip(): issue('blank_name', wid)
        else: names[source['workflowname']].append(wid)
        if table and source['formid'] is not None: shared[(table, source['formid'])].append(wid)
        workflows.append(dict(id=wid, name=source['workflowname'], category_id=source['workflowtype'],
            category_name=category['typename'] if category else None,
            form_id=source['formid'], form_source=table,
            form_table=form.get('tablename') if form else None,
            form_name=form.get('formname') if form else None,
            isbill_raw=selector, isvalid_raw=source['isvalid'], version_raw=source['version'],
            active_version_id_raw=source['activeVersionID'], istemplate_raw=source['istemplate'],
            template_id_raw=source['templateid'], isfree_raw=source['isfree'],
            subcompany_id_raw=source['subcompanyid'],
            source_ref=dict(object='dbo.workflow_base', id=wid)))
    for ids in names.values():
        if len(ids) > 1:
            for wid in ids: issue('duplicate_name', wid)
    return dict(category='B01', normalization_version=METHOD['normalization_version'],
        semantic_state=METHOD['semantics']['state'], workflows=workflows, issues=issues,
        shared_forms=[dict(source=t, form_id=f, workflow_ids=ids)
                      for (t, f), ids in sorted(shared.items()) if len(ids) > 1],
        summary=dict(workflow_count=len(workflows), source_counts={t: len(v) for t, v in tables.items()},
                     issue_counts=dict(Counter(i['kind'] for i in issues)),
                     raw_status_counts=dict(Counter(str(w['isvalid_raw']) for w in workflows))))


def category_dir(root, environment):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', environment):
        raise ValueError('Environment must be a simple stable identifier')
    return Path(root).resolve() / environment / 'B01'


def status(root, environment):
    path = category_dir(root, environment) / 'state.json'
    return read_json(path) if path.exists() else dict(latest_success=None, latest_reviewed=None)


def replace_state(base, state):
    temp = base / ('.state-' + uuid.uuid4().hex + '.json')
    write_json(temp, state)
    os.replace(temp, base / 'state.json')


def load_batch(base, batch_id):
    if not re.fullmatch(r'[0-9TZ-]+-[a-f0-9]{12}', batch_id):
        raise ValueError('Invalid batch identifier')
    path = base / 'batches' / batch_id
    manifest = read_json(path / 'manifest.json')
    for name, expected in manifest['files'].items():
        if Path(name).name != name or hashlib.sha256((path / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Batch integrity check failed')
    return path, manifest


def source_diff(old, new):
    a, b = ({r['id']: r for r in rows} for rows in (old, new))
    return dict(added=sorted(b.keys() - a.keys()), source_missing=sorted(a.keys() - b.keys()),
                changed=[dict(id=k, fields={f: dict(before=a[k].get(f), after=b[k].get(f))
                             for f in sorted(a[k].keys() | b[k].keys()) if a[k].get(f) != b[k].get(f)})
                         for k in sorted(a.keys() & b.keys()) if a[k] != b[k]])


def compare(base, previous, raw, compatibility):
    if not previous:
        return dict(status='baseline', reason='No previous successful batch in this environment')
    path, manifest = load_batch(base, previous)
    old = read_json(path / 'raw.json')
    if capture_time(raw['ended_at']) < capture_time(old['ended_at']):
        raise ValueError('Late older capture rejected; newer successful batch preserved')
    if manifest['compatibility'] != compatibility:
        return dict(status='not_comparable', previous_batch=previous,
                    reason='Source, method, code, schema, normalization or scope changed; review before comparison')
    sources = {t: source_diff(old['tables'][t], raw['tables'][t]) for t in METHOD['tables']}
    return dict(status='compared', previous_batch=previous, sources=sources, **sources['workflow_base'])


def report(path, raw, doc, diff):
    escape = lambda value: html.escape('' if value is None else str(value), quote=True)
    headers = ['流程编号', '流程名称', '分类', '表单ID（原值）', '表单来源', '物理主表/旧式名称',
               '状态原值', '版本原值', '活动版本指针', '模板标志原值', '自由流程标志原值']
    rows = [[w['id'], w['name'], w['category_name'], w['form_id'], w['form_source'],
             w['form_table'] or w['form_name'], w['isvalid_raw'], w['version_raw'],
             w['active_version_id_raw'], w['istemplate_raw'], w['isfree_raw']] for w in doc['workflows']]
    with (path / '流程目录.csv').open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else v for v in row])
    table = '<table><thead><tr>' + ''.join('<th>' + escape(h) + '</th>' for h in headers) + '</tr></thead><tbody>'
    table += ''.join('<tr>' + ''.join('<td>' + escape(v) + '</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table>'
    issue_names = dict(missing_category='分类未匹配', missing_form='表单未匹配',
                       missing_active_version='活动版本指针未匹配', blank_name='空名称',
                       duplicate_name='流程重名（保留各编号）', unknown_form_selector='未知表单类型码')
    counts = Counter((w['category_id'], w['category_name']) for w in doc['workflows'])
    category_text = ''.join('<li>' + escape(name or '未匹配分类') + '（编号' + escape(key) + '）：' + str(count) + '条定义</li>'
                            for (key, name), count in sorted(counts.items(), key=lambda x: str(x[0][0])))
    issues = ''.join('<li>' + escape(issue_names[i['kind']]) + '：流程' + escape(i['workflow_id']) + '</li>' for i in doc['issues'] if i['kind'] != 'duplicate_name') or '<li>未发现分类、表单、活动版本指针悬空或空名称。</li>'
    names = defaultdict(list)
    for w in doc['workflows']: names[w['name']].append(w['id'])
    repeated = [(name, ids) for name, ids in names.items() if len(ids) > 1]
    repeat_text = ''.join('<li>' + escape(name) + '：' + ', '.join(map(str, ids)) + '</li>' for name, ids in repeated) or '<li>无重名。</li>'
    diff_text = '首批基线，不记为全部新增。' if diff['status'] == 'baseline' else '读取口径变化，本批与上批不直接比较。'
    if diff['status'] == 'compared':
        diff_text = f"相对上次成功批次：流程新增{len(diff['added'])}条、修改{len(diff['changed'])}条、来源消失{len(diff['source_missing'])}条。来源消失尚不等于已删除；分类和表单字典变化见diff.json。"
    content = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>B01流程目录审核</title>
<style>body{{font:16px/1.7 system-ui;margin:32px;color:#18222b}}table{{border-collapse:collapse;font-size:14px}}td,th{{border:1px solid #ccd3da;padding:8px;text-align:left}}th{{background:#edf2f6}}.scroll{{overflow:auto}}p{{max-width:1000px}}</style>
<h1>B01 流程目录 · 待审核</h1><p>采集时间：{escape(raw['started_at'])} 至 {escape(raw['ended_at'])}。流程定义共{len(rows)}条；包含不同版本、模板和自由流程相关原始记录，不能直接当成当前可发起流程数量。</p>
<p>范围：当前账号可见的四个配置表，无状态过滤；业务单据读取为0。前后两次配置内容相同，但不代表事务级同一时点快照，也未核对管理员目录的可见范围。</p>
<h2>本次变化</h2><p>{escape(diff_text)}</p><h2>分类分布</h2><ul>{category_text}</ul>
<h2>需要你校准</h2><ol><li>确认目录范围与OA后台一致，是否包含应保留的历史版本、模板或自由流程。</li><li>确认状态码含义和日后默认展示范围。目前全部保留，不自动标记启用或停用。</li><li>确认活动版本指针与版本链的解释。相同名称、相同表单均未自动合并为一个流程。</li><li>表单类型码0目前按旧式表单来源登记，含义仍待平台核对。</li></ol>
<p>状态原值分布：{escape(json.dumps(doc['summary']['raw_status_counts'], ensure_ascii=False))}。共享表单组数：{len(doc['shared_forms'])}；共享仅表示引用相同定义，不表示业务用途相同。</p>
<h2>关联检查</h2><ul>{issues}</ul><h2>重名记录</h2><p>共{len(repeated)}组，涉及{sum(len(ids) for _, ids in repeated)}条定义。可能与版本有关，不能仅凭重名认定重复配置或合并；名称去重数也不代表独立业务流程数量。</p><ul>{repeat_text}</ul><h2>完整流程目录</h2><div class="scroll">{table}</div>
<p>来源：raw.json保留原值、查询范围、结构与分页检查；normalized.json保留标准化目录、关系和问题；manifest.json记录方法、代码和文件哈希。获取成功、语义确认、用户审核分别记录。本文件生成时尚未审核，后续决定见批次外的reviews目录。</p></html>'''
    with (path / '流程目录.html').open('x', encoding='utf-8') as stream:
        stream.write(content)


def publish(root, environment, raw):
    doc = normalize(raw)
    base = category_dir(root, environment)
    base.mkdir(parents=True, exist_ok=True)
    lock = base / '.publish.lock'
    with lock.open('x') as lock_handle:
        try:
            state = status(root, environment)
            compatibility = dict(source=digest(raw['source_identity']), method=raw['method_version'],
                normalization=METHOD['normalization_version'], schema=digest(raw['schema']), scope=METHOD['scope'],
                reader_code=raw.get('implementation_hashes'), normalizer_code=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
            diff = compare(base, state['latest_success'], raw, compatibility)
            batch_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
            pending = base / ('.pending-' + batch_id)
            pending.mkdir()
            write_json(pending / 'raw.json', raw)
            write_json(pending / 'normalized.json', doc)
            write_json(pending / 'diff.json', diff)
            report(pending, raw, doc, diff)
            manifest = dict(batch_id=batch_id, environment=environment, category='B01', created_at=stamp(),
                compatibility=compatibility, reading_state='success', semantic_state=doc['semantic_state'],
                review_state_at_capture='pending', business_rows_read=0,
                files={f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(pending.iterdir())})
            write_json(pending / 'manifest.json', manifest)
            (base / 'batches').mkdir(exist_ok=True)
            target = base / 'batches' / batch_id
            pending.rename(target)
            state['latest_success'] = batch_id
            replace_state(base, state)
            return target
        finally:
            lock_handle.close()
            lock.unlink()


def review(root, environment, batch_id, reviewer, decision, note, semantic_state):
    if decision not in ('accepted', 'needs_revision') or semantic_state not in ('partial', 'confirmed'):
        raise ValueError('Invalid review decision or semantic state')
    if not reviewer.strip() or not note.strip():
        raise ValueError('Review requires named reviewer and explanation')
    base = category_dir(root, environment)
    _, manifest = load_batch(base, batch_id)
    lock = base / '.publish.lock'
    with lock.open('x') as lock_handle:
        try:
            folder = base / 'reviews'
            folder.mkdir(exist_ok=True)
            record = dict(batch_id=batch_id, reviewed_at=stamp(), reviewer=reviewer,
                          decision=decision, note=note, semantic_state=semantic_state,
                          normalization_version=manifest['compatibility']['normalization'])
            write_json(folder / (uuid.uuid4().hex + '.json'), record)
            state = status(root, environment)
            if decision == 'accepted': state['latest_reviewed'] = batch_id
            elif state['latest_reviewed'] == batch_id: state['latest_reviewed'] = None
            replace_state(base, state)
        finally:
            lock_handle.close()
            lock.unlink()


def selected_batch(root, environment, unreviewed=False):
    state = status(root, environment)
    batch_id = state['latest_success' if unreviewed else 'latest_reviewed']
    if not batch_id:
        raise ValueError('No accepted batch; review required (use explicit --unreviewed for inspection)')
    base = category_dir(root, environment)
    path, manifest = load_batch(base, batch_id)
    if not unreviewed and state['latest_success']:
        _, latest = load_batch(base, state['latest_success'])
        if manifest['compatibility']['source'] != latest['compatibility']['source']:
            raise ValueError('Latest capture targets a different source; reviewed knowledge cannot be reused')
    return path
