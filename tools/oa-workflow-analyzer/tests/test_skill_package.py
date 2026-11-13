"""Distribution must be portable and must not include local workflow material."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

from fixtures import write_export

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from package_skill import ANALYZER_FILES, SKILL_FILES, build_package


class SkillPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_only_distribution_inputs_are_packaged_and_hashes_match(self):
        # An independent checkout with realistic local clutter must be safe to share.
        checkout = self.root / "checkout"
        shutil.copytree(ROOT / "skills", checkout / "skills")
        shutil.copytree(ROOT / "src", checkout / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        for name in ("run.py", "pyproject.toml", "AGENT_GUIDE.md", "解析流程.cmd"):
            shutil.copy2(ROOT / name, checkout / name)
        sentinel = "PRIVATE-LOCAL-WORKFLOW-MATERIAL"
        for relative in ("reports/company/workflow.json", "_work/people.csv",
                         ".venv/token.txt", ".env", "private.wewf",
                         "skills/oa-workflow-analysis/private.md",
                         "src/oa_workflow_analyzer/credentials.json"):
            path = checkout / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(sentinel, encoding="utf-8")
        result = build_package(checkout, self.root / "release")
        archive = Path(result["zip"])
        self.assertEqual(archive.read_bytes(), Path(result["skill"]).read_bytes())
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            self.assertTrue(all(n.startswith("oa-workflow-analysis/") for n in names))
            self.assertTrue(all(".." not in Path(n).parts for n in names))
            self.assertFalse(any(n.endswith(".wewf") or "/reports/" in n for n in names))
            self.assertFalse(any(sentinel.encode() in z.read(n) for n in names))
            manifest_name = "oa-workflow-analysis/package-manifest.json"
            manifest = json.loads(z.read(manifest_name))
            self.assertEqual(set(manifest["files"]),
                             {n.removeprefix("oa-workflow-analysis/")
                              for n in names if n != manifest_name})
            for name, info in manifest["files"].items():
                content = z.read("oa-workflow-analysis/" + name)
                self.assertEqual(len(content), info["size"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), info["sha256"])

    def test_extracted_analyzer_runs_without_original_checkout(self):
        result = build_package(ROOT, self.root / "release")
        install = self.root / "新电脑 skill 安装"
        with zipfile.ZipFile(result["zip"]) as z:
            z.extractall(install)
        analyzer = install / "oa-workflow-analysis/scripts/analyzer"
        source_dir = self.root / "独立流程 输入"
        source_dir.mkdir()
        source = write_export(source_dir, name="测试 流程.wewf")
        environment = dict(os.environ)
        for key in ("PYTHONPATH", "OA_WORKFLOW_ANALYZER_HOME", "OA_WORKFLOW_SAMPLE"):
            environment.pop(key, None)
        process = subprocess.run(
            [sys.executable, str(analyzer / "run.py"), str(source),
             "--output", str(self.root / "独立 结果")],
            cwd=install, env=environment, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
        summary = json.loads(process.stdout.decode("utf-8"))
        self.assertEqual(summary["succeeded"], 1)
        output = Path(summary["results"][0]["output_dir"])
        workflow = json.loads((output / "workflow.json").read_text(encoding="utf-8"))
        self.assertEqual(workflow["workflows"][0]["id"], "900")
        self.assertFalse(workflow["analyzer"]["runtime_verified"])
        self.assertTrue((output / "evidence.json").is_file())
        self.assertTrue((output / "report.html").is_file())

    def test_build_is_reproducible(self):
        first = build_package(ROOT, self.root / "first")
        second = build_package(ROOT, self.root / "second")
        self.assertEqual(Path(first["zip"]).read_bytes(), Path(second["zip"]).read_bytes())

    def test_oversized_archive_is_rejected_before_writing_release(self):
        output = self.root / "over-limit"
        with mock.patch("package_skill.MAX_PACKAGE_BYTES", 1000, create=True):
            with self.assertRaises(ValueError):
                build_package(ROOT, output)
        self.assertFalse(output.exists())

    def test_linked_skill_root_cannot_package_external_files(self):
        checkout = self.root / "checkout"
        for relative in ANALYZER_FILES:
            target = checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        external = self.root / "outside-skill-root"
        for relative in SKILL_FILES:
            target = external / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "skills/oa-workflow-analysis" / relative, target)
        marker = "PRIVATE-SENTINEL-FROM-OUTSIDE-SKILL-ROOT"
        with (external / "SKILL.md").open("a", encoding="utf-8") as stream:
            stream.write("\n" + marker + "\n")
        link = checkout / "skills/oa-workflow-analysis"
        link.parent.mkdir(parents=True)
        kind = "symlink"
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                self.skipTest("Directory symbolic links are unavailable")
            process = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(external)],
                capture_output=True)
            if process.returncode:
                self.skipTest("Neither directory symbolic links nor junctions are available")
            kind = "junction"

        def remove_link_only():
            # Registered after TemporaryDirectory cleanup, so it runs first.
            # Remove only the directory entry; never recurse through the link.
            self.assertTrue(link.absolute().is_relative_to(self.root.resolve()))
            if os.path.lexists(link):
                if kind == "junction":
                    os.rmdir(link)
                else:
                    link.unlink()

        self.addCleanup(remove_link_only)
        with self.assertRaises(ValueError):
            build_package(checkout, self.root / "release")

    def test_existing_output_hardlink_does_not_modify_unrelated_file(self):
        baseline = build_package(ROOT, self.root / "baseline")
        release = self.root / "release"
        release.mkdir()
        unrelated = self.root / "unrelated.txt"
        original = b"UNRELATED-FILE-MUST-NOT-BE-OVERWRITTEN"
        unrelated.write_bytes(original)
        target = release / Path(baseline["zip"]).name
        try:
            os.link(unrelated, target)
        except OSError:
            self.skipTest("File hard links are unavailable")
        try:
            build_package(ROOT, release)
        except (OSError, ValueError):
            # Refusing a pre-existing linked target is also a safe outcome.
            pass
        self.assertEqual(unrelated.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
