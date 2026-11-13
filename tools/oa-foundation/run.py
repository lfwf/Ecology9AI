"""Portable registered configuration CLI entry. Credentials never enter Python or model input."""
import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import foundation as f


def refresh(args):
    base = f.category_dir(args.data_root, args.environment)
    attempt = base / 'attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    record = dict(category='B01', started_at=f.stamp(), status='failed', business_rows_read=0)
    stage = 'connection_files'
    try:
        connection = Path(args.connection_directory).resolve()
        if not all((connection / n).is_file() for n in ('connection.json', 'credential.clixml')):
            raise ValueError('Missing connection files')
        stage = 'powershell_runtime'
        shell = shutil.which(args.powershell)
        if not shell:
            raise ValueError('PowerShell not available')
        stage = 'reader'
        result = subprocess.run([shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
            str(f.HOME / METHOD_READER), '-ConnectionDirectory', str(connection),
            '-OutputPath', str(attempt / 'raw.json')],
            capture_output=True, encoding='utf-8', errors='replace', timeout=150, check=False)
        if result.returncode:
            # Reader emits a sanitized fixed stage, never copy arbitrary driver stderr.
            try:
                payload = json.loads(result.stdout.strip())
                allowed = {'initialization','credential','connection','identity','schema','first_pass','second_pass','consistency','save'}
                if payload.get('stage') in allowed: stage = 'reader_' + payload['stage']
                details = payload.get('details')
                if isinstance(details, dict) and details.get('code') == 'schema_contract_mismatch':
                    if details.get('object') in f.METHOD['tables'] and details.get('column') in f.METHOD['tables'][details['object']]:
                        record['gap'] = {key: details.get(key) for key in ('code', 'object', 'column', 'expected_type', 'visible_matches')}
                if type(payload.get('sql_error_number')) is int:
                    record['sql_error_number'] = payload['sql_error_number']
            except (ValueError, AttributeError):
                pass
            raise ValueError('Capture failed')
        stage = 'validation_and_publish'
        batch = f.publish(args.data_root, args.environment, f.read_json(attempt / 'raw.json'))
        record.update(status='success', batch_id=batch.name, report=str(batch / '流程目录.html'))
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        record['failure_stage'] = stage
        record['action'] = 'Check local connection/runtime or registered structure; previous success preserved'
    record['ended_at'] = f.stamp()
    f.write_json(attempt / 'result.json', record)
    return record


METHOD_READER = f.METHOD['reader']


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='OA基础数据：登记类别、批次、差异与审核')
    parser.add_argument('--data-root', type=Path, default=f.HOME / '.local')
    parser.add_argument('--environment', default='oa-local', help='stable logical environment ID')
    parser.add_argument('--category', default='B01', choices=sorted(p.stem for p in (f.HOME / 'registry').glob('B0[1-9].json')))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('method', help='show registered category method; no database connection')
    commands.add_parser('status', help='show separate successful/reviewed pointers')
    read = commands.add_parser('refresh', help='fixed read-only category capture and publication')
    read.add_argument('--connection-directory', required=True)
    read.add_argument('--source-profile', help='B08 local source roots; defaults to source-profile.json beside connection profile')
    read.add_argument('--reference-profile', help='B09 explicit local Java/JSP reference profile; defaults beside connection profile')
    read.add_argument('--powershell', default='pwsh', help='PowerShell executable (Windows DPAPI required)')
    show = commands.add_parser('show', help='locate accepted knowledge; --unreviewed explicitly selects latest capture')
    show.add_argument('--unreviewed', action='store_true')
    review = commands.add_parser('review', help='append user-authorized batch review; never marks raw capture itself')
    review.add_argument('--batch', required=True)
    review.add_argument('--reviewer', required=True)
    review.add_argument('--decision', required=True, choices=['accepted', 'needs_revision'])
    review.add_argument('--note', required=True)
    review.add_argument('--semantic-state', default='partial', choices=['partial', 'confirmed'])
    args = parser.parse_args()
    try:
        if args.category != 'B01':
            from catalog_cli import handle
            value = handle(args)
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return 1 if value.get('status') == 'failed' else 0
        if args.command == 'method': value = f.METHOD
        elif args.command == 'refresh':
            value = refresh(args)
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return 0 if value['status'] == 'success' else 1
        elif args.command == 'status': value = f.status(args.data_root, args.environment)
        elif args.command == 'show':
            batch = f.selected_batch(args.data_root, args.environment, args.unreviewed)
            state = f.status(args.data_root, args.environment)
            value = dict(batch_id=batch.name, report=str(batch / '流程目录.html'),
                         normalized=str(batch / 'normalized.json'), selection='unreviewed_latest' if args.unreviewed else 'accepted',
                         latest_success=state['latest_success'], latest_reviewed=state['latest_reviewed'],
                         has_unreviewed_update=state['latest_success'] != state['latest_reviewed'])
        else:
            f.review(args.data_root, args.environment, args.batch, args.reviewer, args.decision, args.note, args.semantic_state)
            value = f.status(args.data_root, args.environment)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Only local generic errors; no database driver exception reaches this process.
        print(json.dumps(dict(status='failed', error_type=type(error).__name__,
                              action='检查参数、批次完整性或审核状态；未覆盖已有成功结果'), ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
