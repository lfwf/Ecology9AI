"""Run from a checkout, with no package installation required."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
try:
    from oa_workflow_analyzer.cli import main
except ImportError as error:
    print(f"解析器依赖不可用：{error}\n请在此目录运行 python -m pip install -e . 或使用带依赖的 Python 环境。", file=sys.stderr)
    raise SystemExit(2)

if __name__ == "__main__":
    raise SystemExit(main())
