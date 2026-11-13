"""Build a reproducible, portable module-analysis skill from an explicit allowlist."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import tempfile
import zipfile

SKILL_NAME = 'oa-module-analysis'
MAX_PACKAGE_BYTES = 3_000_000
SKILL_FILES = (
    'SKILL.md', 'agents/openai.yaml',
    'references/module-analysis-guide.md', 'references/dictionary-export.md',
)
SUPPORT_FILES = (
    'analyze_module.py', 'pyproject.toml',
    'dictionary/00_discover.sql', 'dictionary/01_physical_metadata.sql',
    'dictionary/02_generate_oa_queries.sql',
)


def read_source(base: Path, relative: str) -> bytes:
    base = base.resolve(strict=True)
    path = base / relative
    for entry in (path, *path.parents):
        if entry == base:
            break
        if entry.is_symlink() or getattr(entry, 'is_junction', lambda: False)():
            raise ValueError(f'Linked distribution input is not allowed: {relative}')
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(base) or not resolved.is_file():
        raise ValueError(f'Invalid distribution input: {relative}')
    return resolved.read_bytes()


def version(content: bytes, pattern: str) -> str:
    result = re.search(pattern, '\n'.join(content.decode('utf-8-sig').splitlines()), re.MULTILINE)
    if not result:
        raise ValueError('Version metadata is missing')
    return result.group(1)


def build_package(tool_root: Path, output_dir: Path) -> dict:
    tool_root = Path(tool_root).resolve(strict=True)
    contents = {name: read_source(tool_root, f'skills/{SKILL_NAME}/{name}') for name in SKILL_FILES}
    contents.update({'scripts/' + name: read_source(tool_root, name) for name in SUPPORT_FILES})
    skill_version = version(contents['SKILL.md'], r'^  version: "(\d+\.\d+\.\d+)"$')
    analyzer_version = version(contents['scripts/pyproject.toml'], r'^version = "(\d+\.\d+\.\d+)"$')
    manifest = {
        'format_version': 1, 'skill_name': SKILL_NAME, 'skill_version': skill_version,
        'analyzer_version': analyzer_version,
        'files': {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(contents.items())},
    }
    contents['package-manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    memory = BytesIO()
    with zipfile.ZipFile(memory, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(SKILL_NAME + '/' + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    payload = memory.getvalue()
    if len(payload) >= MAX_PACKAGE_BYTES:
        raise ValueError(f'Skill archive must be smaller than {MAX_PACKAGE_BYTES} bytes; got {len(payload)}')
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for extension in ['zip', 'skill']:
        target = output_dir / f'{SKILL_NAME}-{skill_version}.{extension}'
        pending = None
        try:
            with tempfile.NamedTemporaryFile(dir=output_dir, prefix='.' + SKILL_NAME + '-', suffix='.tmp', delete=False) as stream:
                pending = Path(stream.name)
                stream.write(payload)
            pending.replace(target)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
        paths[extension] = str(target)
    return {'skill_name': SKILL_NAME, 'skill_version': skill_version,
            'analyzer_version': analyzer_version, 'file_count': len(contents),
            'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(), **paths}


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=root / 'dist')
    args = parser.parse_args()
    try:
        result = build_package(root, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Skill packaging failed: {error}\n')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
