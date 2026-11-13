import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def load_tool(self):
        path = ROOT / 'package_skill.py'
        self.assertTrue(path.exists(), 'Portable module skill packager is not implemented')
        spec = importlib.util.spec_from_file_location('module_skill_package', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self, root, module):
        for name in module.SKILL_FILES:
            file = root / 'skills/oa-module-analysis' / name
            file.parent.mkdir(parents=True, exist_ok=True)
            text = 'reference\n'
            if name == 'SKILL.md':
                text = '---\nname: oa-module-analysis\ndescription: Module test\nmetadata:\n  version: "1.0.0"\n---\n'
            file.write_text(text, encoding='utf-8')
        for name in module.SUPPORT_FILES:
            file = root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('version = "0.1.0"\n' if name == 'pyproject.toml' else '# public helper\n', encoding='utf-8')
        secret = root / 'reports/private-attendance.txt'
        secret.parent.mkdir()
        secret.write_text('Private record must never enter a skill package', encoding='utf-8')

    def test_reproducible_allowlist_and_manifest(self):
        module = self.load_tool()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'tool'; root.mkdir()
            self.fixture(root, module)
            first = module.build_package(root, root / 'release')
            payload = Path(first['zip']).read_bytes()
            second = module.build_package(root, root / 'release')
            self.assertEqual(payload, Path(second['zip']).read_bytes())
            self.assertEqual(payload, Path(second['skill']).read_bytes())
            self.assertLess(len(payload), 3_000_000)
            with zipfile.ZipFile(first['zip']) as archive:
                prefix = 'oa-module-analysis/'
                manifest = json.loads(archive.read(prefix + 'package-manifest.json'))
                self.assertEqual(set(archive.namelist()), {prefix + name for name in manifest['files']} | {prefix + 'package-manifest.json'})
                for name, info in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(archive.read(prefix + name)).hexdigest(), info['sha256'])
                self.assertFalse(any('private' in name or 'reports' in name for name in archive.namelist()))

    def test_output_hardlink_is_replaced_without_touching_target(self):
        module = self.load_tool()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'tool'; root.mkdir(); self.fixture(root, module)
            release = root / 'release'; release.mkdir()
            private = root / 'unrelated.txt'; private.write_bytes(b'preserve')
            os.link(private, release / 'oa-module-analysis-1.0.0.zip')
            module.build_package(root, release)
            self.assertEqual(private.read_bytes(), b'preserve')

    def test_size_guard_precedes_output_writes(self):
        module = self.load_tool()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'tool'; root.mkdir(); self.fixture(root, module)
            module.MAX_PACKAGE_BYTES = 1
            with self.assertRaises(ValueError):
                module.build_package(root, root / 'release')
            self.assertFalse((root / 'release').exists())


if __name__ == '__main__':
    unittest.main()
