"""Batch-friendly JSON CLI. Export contents never become commands."""
import argparse
import json
from pathlib import Path
import re
import sys

from . import __version__
from .analyzer import analyze_export
from .output import OutputError, write_analysis


def _inputs(paths, recursive):
    found, failures, seen = [], [], set()
    for value in paths:
        path = Path(value).absolute()
        try:
            if path.is_dir():
                candidates = sorted(path.rglob("*") if recursive else path.iterdir(), key=lambda x: str(x).casefold())
                candidates = [x for x in candidates if x.is_file() and x.suffix.casefold() in {".wewf", ".xml", ".exml"}]
                if not candidates:
                    failures.append({"input": str(path), "status": "error", "code": "NO_INPUT", "message": "文件夹中没有流程导出文件"})
            else:
                candidates = [path]
        except OSError as error:
            failures.append({"input": str(path), "status": "error", "code": "INPUT_IO", "message": str(error)})
            continue
        for candidate in candidates:
            try:
                resolved = str(candidate.resolve())
            except OSError as error:
                failures.append({"input": str(candidate), "status": "error", "code": "INPUT_IO", "message": str(error)})
                continue
            key = resolved.casefold() if sys.platform == "win32" else resolved
            if key not in seen:
                seen.add(key)
                found.append(candidate)
    return found, failures


def _publish(result, output, source, pdf):
    stem = re.sub(r"[^\w.-]", "_", source.stem).strip(". ")[:40] or "export"
    language = re.sub(r"[^\w-]", "_", result["analyzer"]["language"])[:20]
    base = output / f"workflow-{stem}-{result['source']['sha256'][:12]}-{language}{'-pdf' if pdf else ''}"
    for number in range(1, 1001):
        directory = base if number == 1 else base.with_name(base.name + f"-{number}")
        try:
            return write_analysis(result, directory, pdf=pdf)
        except OutputError as error:
            if error.code not in {"OUTPUT_MODIFIED", "OUTPUT_CONFLICT"}:
                raise
    raise OutputError("OUTPUT_CONFLICT", "同名输出过多，请指定新的 --output 目录")


def main(argv=None):
    # JSON consumers must get UTF-8 even when Windows redirects stdout using
    # the legacy locale encoding. Do this at the CLI boundary, not on import.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="离线解析 OA .wewf/.xml，生成说明书、证据和缺失清单；不会导入或执行流程。")
    parser.add_argument("inputs", nargs="+", help="文件或文件夹，可一次提供多个")
    parser.add_argument("--output", type=Path, default=Path.cwd() / "reports", help="输出根目录，默认当前目录 reports")
    parser.add_argument("--language", default="7", help="优先标签语言 ID，默认7简体中文")
    parser.add_argument("--recursive", action="store_true", help="递归查找输入文件夹")
    parser.add_argument("--pdf", action="store_true", help="同时生成 PDF，需要可选 reportlab 依赖")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    sources, results = _inputs(args.inputs, args.recursive)
    for source in sources:
        try:
            result = analyze_export(source, language=args.language)
            written = _publish(result, args.output.absolute(), source, args.pdf)
            results.append({"input": str(source), "status": result["summary"]["status"], **written})
        except Exception as error:
            # A failing file remains visible and does not cancel other files.
            results.append({"input": str(source), "status": "error", "code": getattr(error, "code", "ANALYSIS_ERROR"), "message": str(error)})
    failed = sum(x["status"] == "error" for x in results)
    print(json.dumps({"schema_version": "1.0", "succeeded": len(results) - failed, "failed": failed, "results": results}, ensure_ascii=False))
    return 1 if failed else 0
