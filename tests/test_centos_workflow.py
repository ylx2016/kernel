"""CentOS workflow regression tests, without Docker or network access.

The receiver is extracted from the real workflow and run against ordinary
sentinel files. This tests path/type handling, not RPM format or EL8 booting.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

import test_debian_workflow


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/Centos_kernel_latest.yml"


class CentosReleaseDedupTests(test_debian_workflow.ReleaseDedupTests):
    workflow = WORKFLOW
    release_prefix = "CentOS_Kernel_Cloud_"


class RpmReceiverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        yq = shutil.which("yq")
        if yq is None:
            raise RuntimeError("mikefarah/yq is required")
        cls.workflow = json.loads(subprocess.run(
            [yq, "-o=json", ".", str(WORKFLOW)], check=True,
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        ).stdout)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rpm-receiver-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.source = self.work / "rpm-output"
        self.arch = self.source / "x86_64"
        self.arch.mkdir(parents=True)
        self.destination = self.work / "upload"
        self.destination.mkdir()
        self.names = [f"{name}-7.3.3-2.el8.x86_64.rpm"
                      for name in ("kernel", "kernel-devel", "kernel-headers")]
        for name in self.names:
            (self.arch / name).write_bytes((name + "\nfixture payload\n").encode())

    def receive(self):
        steps = self.workflow["jobs"]["build"]["steps"]
        step = next((step for step in steps if step["name"] == "Collect RPM artifacts"), {})
        match = re.search(r"<<'PY'\n(.*?)\nPY(?:\n|$)", step.get("run", ""), re.S)
        self.assertIsNotNone(match, "The workflow is missing the RPM receiver")
        # Execute the same program the workflow uses, not a test reimplementation.
        program = textwrap.dedent(match.group(1))
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
        env.update(HOME=str(self.work), TMP=str(self.work), TEMP=str(self.work))
        return subprocess.run(
            [sys.executable, "-I", "-c", program, str(self.source),
             str(self.destination), "7.3.3"],
            cwd=self.work, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )

    def assert_rejected(self):
        result = self.receive()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(self.destination.iterdir()), [],
                         "Validate the complete input set before publishing any file")

    def test_valid_set_is_copied_byte_for_byte(self):
        result = self.receive()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(path.name for path in self.destination.iterdir()), sorted(self.names))
        for name in self.names:
            self.assertEqual((self.destination / name).read_bytes(), (self.arch / name).read_bytes())

    def test_missing_or_unexpected_package_is_rejected(self):
        for bad in ("missing", "extra", "wrong-version", "wrong-arch", "wrong-dist", "mixed-release", "empty"):
            with self.subTest(case=bad):
                path = self.arch / self.names[0]
                original = path.read_bytes()
                other = None
                if bad == "missing":
                    path.unlink()
                elif bad == "empty":
                    path.write_bytes(b"")
                else:
                    name = {"extra": "unexpected.rpm",
                            "wrong-version": "kernel-7.3.2-2.el8.x86_64.rpm",
                            "wrong-arch": "kernel-7.3.3-2.el8.aarch64.rpm",
                            "wrong-dist": "kernel-7.3.3-2.el9.x86_64.rpm",
                            "mixed-release": "kernel-7.3.3-3.el8.x86_64.rpm"}[bad]
                    if bad != "extra":
                        # Replace, rather than add, so a package-count check cannot
                        # accidentally hide a broken version/architecture validator.
                        path.unlink()
                    other = self.arch / name
                    other.write_bytes(b"unexpected payload")
                try:
                    self.assert_rejected()
                finally:
                    if other:
                        other.unlink()
                    path.write_bytes(original)

    def test_hardlinked_package_is_rejected(self):
        path = self.arch / self.names[0]
        os.link(path, self.work / "outside-hardlink")
        self.assert_rejected()

    def test_nested_directory_is_rejected(self):
        (self.arch / "nested").mkdir()
        self.assert_rejected()

    def test_symlinked_package_or_directory_is_rejected(self):
        probe = self.work / "probe"
        try:
            probe.symlink_to(self.arch, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Host cannot create symlinks: {error}")
        probe.unlink()
        for target in ("package", "arch", "source"):
            with self.subTest(target=target):
                path = {"package": self.arch / self.names[0],
                        "arch": self.arch, "source": self.source}[target]
                saved = self.work / ("saved-" + target)
                path.rename(saved)
                path.symlink_to(saved, target_is_directory=(target != "package"))
                try:
                    self.assert_rejected()
                finally:
                    path.unlink()
                    saved.rename(path)


if __name__ == "__main__":
    unittest.main()
