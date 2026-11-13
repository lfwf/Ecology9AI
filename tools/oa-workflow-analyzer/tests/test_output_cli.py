import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from fixtures import write_export
try:
    from oa_workflow_analyzer.output import write_analysis, OutputError
    from oa_workflow_analyzer.analyzer import analyze_export
except ImportError:
    write_analysis = None
    analyze_export = None
    OutputError = ValueError


class OutputCliTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(write_analysis, "Bundle writer and CLI are not implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "oa_workflow_analyzer", *map(str, args)], capture_output=True, text=True, encoding="utf-8")

    def test_all_artifacts_manifest_and_cache_are_verified(self):
        result = analyze_export(write_export(self.root))
        directory = self.root / "结果"
        first = write_analysis(result, directory)
        self.assertFalse(first["cached"])
        expected = {"workflow.json", "evidence.json", "missing-data.json", "agent-context.json", "report.md", "report.html", "manifest.json"}
        self.assertEqual({x.name for x in directory.iterdir()}, expected)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["files"]), expected - {"manifest.json"})
        self.assertTrue(write_analysis(result, directory)["cached"])
        agent = json.loads((directory / "agent-context.json").read_text(encoding="utf-8"))
        self.assertEqual(agent["input_trust"], "untrusted_export_data")

    def test_arbitrary_existing_files_and_modified_reports_are_not_overwritten(self):
        result = analyze_export(write_export(self.root))
        target = self.root / "existing"
        target.mkdir()
        (target / "keep.txt").write_text("user-data")
        with self.assertRaises(OutputError):
            write_analysis(result, target)
        self.assertEqual((target / "keep.txt").read_text(), "user-data")
        other = self.root / "generated"
        write_analysis(result, other)
        (other / "report.md").write_text("user edits", encoding="utf-8")
        with self.assertRaises(OutputError):
            write_analysis(result, other)
        self.assertEqual((other / "report.md").read_text(encoding="utf-8"), "user edits")

    def test_cli_single_repeat_and_tampered_cache_regeneration(self):
        source = write_export(self.root)
        output = self.root / "reports"
        one = self.cli(source, "--output", output)
        self.assertEqual(one.returncode, 0, one.stderr)
        first = json.loads(one.stdout)["results"][0]
        repeat = self.cli(source, "--output", output)
        self.assertTrue(json.loads(repeat.stdout)["results"][0]["cached"])
        first_dir = Path(first["output_dir"])
        (first_dir / "report.md").write_text("manual edit", encoding="utf-8")
        rerun = self.cli(source, "--output", output)
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertNotEqual(json.loads(rerun.stdout)["results"][0]["output_dir"], str(first_dir))
        self.assertEqual((first_dir / "report.md").read_text(encoding="utf-8"), "manual edit")

    def test_batch_failure_does_not_block_successful_file(self):
        write_export(self.root)
        (self.root / "坏文件.wewf").write_text("not-zip")
        process = self.cli(self.root, "--output", self.root / "output")
        self.assertEqual(process.returncode, 1, process.stderr)
        summary = json.loads(process.stdout)
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertTrue(any(x["status"] == "error" and x["code"] == "BAD_ARCHIVE" for x in summary["results"]))

    def test_launcher_runs_without_installed_package(self):
        package = Path(__file__).resolve().parents[1]
        self.assertTrue((package / "run.py").is_file())
        source = write_export(self.root)
        process = subprocess.run([sys.executable, str(package / "run.py"), str(source), "--output", str(self.root / "out")], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["succeeded"], 1)

    def test_cli_json_is_utf8_without_python_encoding_environment(self):
        source = write_export(self.root)
        environment = dict(os.environ)
        environment.pop("PYTHONIOENCODING", None)
        environment.pop("PYTHONUTF8", None)
        process = subprocess.run(
            [sys.executable, "-X", "utf8=0", "-m", "oa_workflow_analyzer", str(source), "--output", str(self.root / "中文结果")],
            capture_output=True, env=environment)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))["succeeded"], 1)

    @unittest.skipUnless(sys.platform == "win32", "Windows drag/drop entry")
    def test_windows_command_accepts_unicode_and_space_paths(self):
        package = Path(__file__).resolve().parents[1]
        source = write_export(self.root, name="另一个 流程.wewf")
        environment = dict(os.environ, OA_WORKFLOW_PYTHON=sys.executable)
        process = subprocess.run(
            ["cmd.exe", "/d", "/c", str(package / "解析流程.cmd"), str(source), "--output", str(self.root / "中文 结果")],
            capture_output=True, env=environment)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))["succeeded"], 1)


if __name__ == "__main__":
    unittest.main()
