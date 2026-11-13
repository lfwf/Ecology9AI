"""Validate and build a WorkBuddy expert ZIP. Development dependency: PyYAML."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

import yaml

BASE = Path(__file__).resolve().parent
ROOT = BASE / 'oa-workflow-expert'
REQUIRED = ['name', 'version', 'description', 'author', 'agents', 'expertType', 'agentName', 'displayName', 'profession', 'displayDescription', 'avatar', 'categoryId', 'defaultInitPrompt', 'plugin', 'tags', 'quickPrompts']
CATEGORIES = {'01-ProductDesign', '02-Engineering', '03-GameSpatial', '04-DataAI', '05-MarketingGrowth', '06-ContentCreative', '07-SalesCommerce', '08-FinanceInvestment', '09-OperationsHR', '10-ProjectQuality', '11-SecurityCompliance', '12-IndustryConsultant', '13-TencentZone', '14-WorldWise', '15-Education'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def files(root):
    return sorted(p for p in root.rglob('*') if p.is_file() and not any(part in {'__pycache__', '.venv', '__MACOSX', '.git'} for part in p.relative_to(root).parts) and p.suffix not in {'.pyc', '.pyo'} and p.name != '.DS_Store')


def local_path(root, path):
    require(isinstance(path, str), 'Reference must be a relative path string')
    pure = PurePosixPath(path)
    require(not pure.is_absolute() and '..' not in pure.parts and '\\' not in path and ':' not in path, 'Unsafe package path: ' + path)
    target = (root / path).resolve()
    require(target.is_relative_to(root.resolve()) and target.exists(), 'Missing package path: ' + path)
    return target


def frontmatter(path):
    text = path.read_text('utf-8')
    require(text.startswith('---\n'), 'Missing YAML frontmatter: ' + str(path))
    _, head, body = text.split('---', 2)
    data = yaml.safe_load(head)
    require(isinstance(data, dict) and bool(body.strip()), 'Invalid agent/skill document')
    return data


def bilingual(value, name):
    require(isinstance(value, dict) and all(isinstance(value.get(lang), str) and value[lang].strip() for lang in ['zh', 'en']), 'Missing bilingual text: ' + name)


def validate(root):
    plugin = json.loads((root / '.codebuddy-plugin/plugin.json').read_text('utf-8'))
    require(set(REQUIRED) <= plugin.keys(), 'Missing required plugin fields')
    require(re.fullmatch('[a-z]+(?:-[a-z]+)*', plugin['name']), 'Invalid expert name')
    require(plugin['plugin'] == plugin['name'] == root.name, 'Plugin and directory names must match')
    require(re.fullmatch(r'\d+\.\d+\.\d+', plugin['version']), 'Invalid version')
    require(plugin['expertType'] == 'agent', 'Expected one agent')
    require(plugin['categoryId'] in CATEGORIES, 'Outdated/invalid category')
    require(plugin['author']['name'].strip() and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', plugin['author']['email']), 'Author name and email required')
    require(not any(x in json.dumps(plugin) for x in ['Your Name', 'you@example.com', 'TODO']), 'Unfilled metadata placeholder')
    for key in ['displayName', 'profession', 'displayDescription', 'defaultInitPrompt']:
        bilingual(plugin[key], key)
    description_length = len(plugin['displayDescription']['zh'])
    require(40 <= description_length <= 50, f'Chinese description must be 40–50 characters, got {description_length}')
    for key in ['tags', 'quickPrompts']:
        require(len(plugin[key]) == 3, key + ' must contain exactly three items')
        for item in plugin[key]:
            bilingual(item, key)
    require(plugin['defaultInitPrompt'] == plugin['quickPrompts'][0], 'Initial prompt must equal the first quick prompt')
    require(len(plugin['agents']) == 1, 'Expected a single primary agent')
    agent_path = local_path(root, plugin['agents'][0])
    agent = frontmatter(agent_path)
    require(agent_path.stem == plugin['agentName'] == agent['name'], 'Agent name mismatch')
    require('tools' not in agent, 'Do not declare agent tools; WorkBuddy assigns them')
    for key in ['displayName', 'profession']:
        bilingual(agent[key], 'agent.' + key)
        require(agent[key] == plugin[key], 'Agent display metadata differs from plugin')
    skill_names = []
    for relative in plugin.get('skills', []):
        skill_path = local_path(root, relative)
        skill = frontmatter(skill_path / 'SKILL.md')
        for key in ['name', 'display_name', 'display_name_en', 'description', 'description_zh', 'description_en', 'version', 'author']:
            require(bool(skill.get(key)), 'Missing required skill field: ' + key)
        require(skill['name'] == skill_path.name, 'Skill directory/name mismatch')
        skill_names.append(skill['name'])
    require(set(agent.get('skills', [])) <= set(skill_names), 'Agent preloads an unpackaged skill')
    avatar = local_path(root, plugin['avatar'])
    raw = avatar.read_bytes()
    require(raw.startswith(b'\x89PNG\r\n\x1a\n'), 'Expected PNG avatar')
    require(struct.unpack('>II', raw[16:24]) == (512, 512), 'Avatar must be 512x512')
    require(len(raw) <= 500 * 1024, 'Avatar exceeds 500KB')
    paths = files(root)
    for p in paths:
        require(p.suffix.lower() not in {'.wewf', '.exml', '.class', '.jar'}, 'Business input or binary unexpectedly packaged: ' + str(p))
        require(p.name not in {'workflow.json', 'evidence.json', 'agent-context.json', 'technical-evidence.json'}, 'Business analysis output unexpectedly packaged')
        if p.suffix in {'.py', '.md', '.json', '.cmd'}:
            text = p.read_text('utf-8')
            require(not re.search(r'(?i)[a-z]:[/\\]+users[/\\]+', text), 'Personal home path in package: ' + str(p))
    return {'name': plugin['name'], 'version': plugin['version'], 'file_count': len(paths), 'description_zh_characters': description_length, 'avatar_bytes': len(raw)}


def build(root, destination):
    summary = validate(root)
    entries = {}
    for p in files(root):
        if p.name == 'package-manifest.json':
            continue
        raw = p.read_bytes()
        entries[p.relative_to(root).as_posix()] = {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    manifest = {'format': 'workbuddy-expert-package-manifest-v1', 'name': summary['name'], 'version': summary['version'], 'files': entries}
    (root / 'package-manifest.json').write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{summary['name']}-{summary['version']}.zip"
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for p in files(root):
            info = ZipInfo(root.name + '/' + p.relative_to(root).as_posix(), (2026, 11, 2, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, p.read_bytes())
    require(output.stat().st_size < 3_000_000, 'Distribution ZIP exceeds the source skill size target')
    with ZipFile(output) as archive:
        require(archive.testzip() is None, 'ZIP CRC validation failed')
        for path, spec in manifest['files'].items():
            require(hashlib.sha256(archive.read(root.name + '/' + path)).hexdigest() == spec['sha256'], 'ZIP manifest mismatch')
    return {**summary, 'zip': str(output), 'bytes': output.stat().st_size, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=BASE / 'dist')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        result = validate(args.root) if args.check else build(args.root, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
