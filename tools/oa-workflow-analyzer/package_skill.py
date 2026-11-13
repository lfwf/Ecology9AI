"""Build a portable skill from explicit source files, never from local reports.

The .skill and .zip outputs are identical ZIP containers. Building needs only
the Python standard library; using the bundled analyzer needs its dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import tempfile
import zipfile


SKILL_NAME = "oa-workflow-analysis"
MAX_PACKAGE_BYTES = 3_000_000
SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "INSTALL.md",
    "references/analysis-guide.md",
    "references/semantic-checks.md",
    "references/review-checklist-v2.md",
    "references/review-method.md",
)
ANALYZER_FILES = (
    "run.py",
    "解析流程.cmd",
    "pyproject.toml",
    "AGENT_GUIDE.md",
    "src/oa_workflow_analyzer/__init__.py",
    "src/oa_workflow_analyzer/__main__.py",
    "src/oa_workflow_analyzer/analyzer.py",
    "src/oa_workflow_analyzer/archive.py",
    "src/oa_workflow_analyzer/cli.py",
    "src/oa_workflow_analyzer/normalize.py",
    "src/oa_workflow_analyzer/output.py",
    "src/oa_workflow_analyzer/reports.py",
    "src/oa_workflow_analyzer/scripts.py",
    "src/oa_workflow_analyzer/schemas/workflow.schema.json",
)


def read_source(base: Path, relative: str) -> bytes:
    """Reject linked distribution inputs rather than copying arbitrary material."""
    base = base.resolve(strict=True)
    path = base / relative
    for item in (path, *path.parents):
        if item == base:
            break
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError(f"Linked distribution input is not allowed: {relative}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(base) or not resolved.is_file():
        raise ValueError(f"Invalid distribution input: {relative}")
    return resolved.read_bytes()


def version_from(content: bytes, pattern: str, description: str) -> str:
    match = re.search(pattern, content.decode("utf-8-sig"), re.MULTILINE)
    if not match:
        raise ValueError(f"Missing {description} version")
    return match.group(1)


def build_package(tool_root: Path, output_dir: Path) -> dict:
    tool_root = Path(tool_root).resolve(strict=True)
    contents = {name: read_source(tool_root, f"skills/{SKILL_NAME}/{name}")
                for name in SKILL_FILES}
    contents.update({"scripts/analyzer/" + name: read_source(tool_root, name)
                     for name in ANALYZER_FILES})
    version = version_from(contents["SKILL.md"],
                           r'^  version: "(\d+\.\d+\.\d+)"$', "skill")
    analyzer_version = version_from(contents["scripts/analyzer/pyproject.toml"],
                                    r'^version = "(\d+\.\d+\.\d+)"$', "analyzer")
    manifest = {
        "format_version": 1,
        "skill_name": SKILL_NAME,
        "skill_version": version,
        "analyzer_version": analyzer_version,
        "files": {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(contents.items())},
    }
    contents["package-manifest.json"] = (json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(SKILL_NAME + "/" + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    payload = buffer.getvalue()
    if len(payload) >= MAX_PACKAGE_BYTES:
        raise ValueError(f"Skill archive must be smaller than {MAX_PACKAGE_BYTES} bytes; got {len(payload)}")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for extension in ("zip", "skill"):
        target = output_dir / f"{SKILL_NAME}-{version}.{extension}"
        # Replace this directory entry, never write through an existing hard link.
        pending = None
        try:
            with tempfile.NamedTemporaryFile(dir=output_dir, prefix=f".{SKILL_NAME}-",
                                             suffix=".tmp", delete=False) as stream:
                pending = Path(stream.name)
                stream.write(payload)
            pending.replace(target)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
        paths[extension] = str(target)
    return {"skill_name": SKILL_NAME, "skill_version": version,
            "analyzer_version": analyzer_version, "file_count": len(contents),
            "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), **paths}


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "dist")
    args = parser.parse_args()
    try:
        result = build_package(root, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Skill packaging failed: {error}\n")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
