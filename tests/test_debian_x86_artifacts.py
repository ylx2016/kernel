"""Debian x86 handoff regressions: real workflow shell, local CLI/file fixtures.

No Docker, GitHub, kernel build or installation is performed. Native tar/od
process fixture payloads; dpkg-deb is represented by its documented CLI output.
"""
import ast
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/Debian_kernel_latest.yml"
PACKAGES = ("linux-image-7.3.3", "linux-headers-7.3.3", "linux-libc-dev")
FILENAMES = tuple(name + "_7.3.3-2_amd64.deb" for name in PACKAGES)
ELF = b"\x7fELF\x02\x01\x01" + bytes(11) + b"\x3e\x00" + bytes(44)
IMAGE = bytearray(1024)
IMAGE[510:512] = b"\x55\xaa"
IMAGE[514:518] = b"HdrS"
BASE_ID = "sha256:" + "a" * 64


class DebianX86ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        cls.doc = json.loads(subprocess.run(
            [shutil.which("yq"), "-o=json", ".", str(WORKFLOW)], check=True,
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        ).stdout)
        cls.steps = {step["name"]: step for step in cls.doc["jobs"]["build"]["steps"]}

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="debian-x86-artifacts-")
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.workspace, self.runner = self.work / "workspace", self.work / "runner"
        self.workspace.mkdir()
        self.runner.mkdir()
        self.upload = self.workspace / "upload"
        self.upload.mkdir()
        for name in FILENAMES:
            (self.upload / name).write_bytes(b"fixture package")
        self.env_file = self.runner / "github-env"
        self.env_file.touch()
        self.trace = self.runner / "trace"
        self.env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR")
                    if key in os.environ}
        self.env.update(HOME=self.runner.as_posix(), TMP=self.runner.as_posix(),
                        TEMP=self.runner.as_posix(), TMPDIR=self.runner.as_posix(), LC_ALL="C.UTF-8",
                        GITHUB_WORKSPACE=self.workspace.as_posix(), RUNNER_TEMP=self.runner.as_posix(),
                        GITHUB_ENV=self.env_file.as_posix(), UPLOAD_PATH=self.upload.as_posix(),
                        KERNEL_VER="7.3.3",
                        RELEASE_TAG="fixture-release",
                        GITHUB_REPOSITORY="fixture/kernel",
                        GITHUB_SHA="c" * 40, BUILD_BASE_IMAGE_ID=BASE_ID,
                        BUILD_CONTAINER="builder", VERIFY_CONTAINER="verifier",
                        BUILD_IMAGE="debian:12-slim", BUILD_ARCH="linux/amd64",
                        TEST_PYTHON=Path(sys.executable).as_posix(), TRACE=self.trace.as_posix())

    def body(self, name):
        self.assertTrue(name in self.steps, "Missing step: " + name)
        body = self.steps[name]["run"]
        # GitHub expression expansion precedes shell execution. Keep the fixture
        # environment uppercase-only: Windows cannot preserve case-only aliases.
        for key, value in {"kernel_ver": "7.3.3", "release_tag": "fixture-release"}.items():
            body = body.replace("${{ env." + key + " }}", value)
        return body

    def run_step(self, name, prefix=""):
        return subprocess.run([self.bash, "--noprofile", "--norc"],
                              input=prefix + "\n" + self.body(name), cwd=self.runner, env=self.env,
                              text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=30)

    def values(self):
        return dict(line.split("=", 1) for line in self.env_file.read_text().splitlines())

    def collect(self):
        return self.run_step("Collect deb artifacts", 'python3() { "$TEST_PYTHON" "$@"; }')

    def test_collection_does_not_authorize_upload(self):
        result = self.collect()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        values = self.values()
        snapshot = Path(values["UPLOAD_PATH"])
        self.assertTrue(snapshot.is_relative_to(self.runner))
        self.assertNotIn("compile_status", values)
        self.assertEqual({p.name for p in snapshot.iterdir()}, set(FILENAMES))
        for name in FILENAMES:
            self.assertEqual((snapshot / name).read_bytes(), (self.upload / name).read_bytes())

    def test_receiver_rejects_foreign_architecture(self):
        original = self.upload / FILENAMES[0]
        original.rename(original.with_name(FILENAMES[0].replace("_amd64", "_arm64")))
        result = self.collect()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("UPLOAD_PATH", self.values())

    def test_receiver_rejects_hardlinks(self):
        os.link(self.upload / FILENAMES[0], self.work / "other-link")
        result = self.collect()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("UPLOAD_PATH", self.values())

    def test_receiver_rejects_source_directory_symlink(self):
        real = self.workspace / "real-upload"
        self.upload.rename(real)
        try:
            self.upload.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(str(error))
        result = self.collect()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("UPLOAD_PATH", self.values())

    def test_failed_stop_blocks_handoff(self):
        result = self.run_step("Stop builder before collecting artifacts", "docker() { return 42; }")
        self.assertEqual(result.returncode, 42)
        self.assertEqual(self.values(), {})

    def prepare_verifier(self, arch="amd64", helper=ELF, image=bytes(IMAGE)):
        fixtures = self.work / "fixtures"
        fixtures.mkdir()
        metadata = {filename: {"Package": name, "Version": "7.3.3-2", "Architecture": arch}
                    for filename, name in zip(FILENAMES, PACKAGES)}
        (fixtures / "metadata.json").write_text(json.dumps(metadata))
        root = "./usr/src/linux-headers-7.3.3/"
        members = (
            [("./boot/vmlinuz-7.3.3", image)],
            [(root + "Makefile", b"headers"), (root + "scripts/basic/fixdep", helper),
             (root + "scripts/mod/modpost", helper)],
            [("./usr/include/linux/types.h", b"types")],
        )
        for filename, entries in zip(FILENAMES, members):
            with tarfile.open(fixtures / (filename + ".tar"), "w") as archive:
                for name, data in entries:
                    item = tarfile.TarInfo(name)
                    item.size, item.mode = len(data), 0o644
                    archive.addfile(item, io.BytesIO(data))
        cli = self.work / "dpkg_fixture.py"
        cli.write_text('''import json, os, pathlib, sys
root = pathlib.Path(os.environ["FIXTURES"])
args = sys.argv[1:]
if args[0] == "-f":
    values = json.loads((root / "metadata.json").read_text())[pathlib.Path(args[1]).name]
    for field in args[2:]:
        print((field + ": " if len(args[2:]) > 1 else "") + values[field])
elif args[0] == "--fsys-tarfile":
    sys.stdout.buffer.write((root / (pathlib.Path(args[1]).name + ".tar")).read_bytes())
else:
    raise SystemExit("Unexpected dpkg-deb arguments")
''')
        self.env.update(FIXTURES=fixtures.as_posix(), TEST_CLI=cli.as_posix())
        self.env["VERIFIER_PREFIX"] = '''
cd() { if [ "$1" = /packages ]; then builtin cd "$UPLOAD_PATH"; else builtin cd "$@"; fi; }
dpkg-deb() { "$TEST_PYTHON" -I -B "$TEST_CLI" "$@"; }
'''
        if os.name == "nt":
            self.env["VERIFIER_PREFIX"] += '\nulimit() { [ "$*" = "-f 196608" ]; }\n'

    def validate(self):
        return self.run_step("Validate final deb artifacts", '''
docker() {
    printf '%s\\n' "$@" > "$TRACE"
    { printf '%s\\n' "$VERIFIER_PREFIX"; command cat; } | command bash --noprofile --norc
}
''')

    def test_valid_snapshot_uses_readonly_verifier(self):
        self.prepare_verifier()
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.values().get("compile_status"), "success")
        args = self.trace.read_text().splitlines()
        self.assertIn(BASE_ID, args)
        self.assertIn("--read-only", args)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertIn("type=bind,source=" + self.env["UPLOAD_PATH"] + ",target=/packages,readonly", args)

    def test_foreign_metadata_blocks_upload(self):
        self.prepare_verifier(arch="arm64")
        self.assertNotEqual(self.validate().returncode, 0)
        self.assertNotIn("compile_status", self.values())

    def test_foreign_helper_blocks_upload(self):
        self.prepare_verifier(helper=ELF[:18] + b"\xb7\x00" + ELF[20:])
        self.assertNotEqual(self.validate().returncode, 0)
        self.assertNotIn("compile_status", self.values())

    def test_bad_kernel_image_blocks_upload(self):
        self.prepare_verifier(image=bytes(1024))
        self.assertNotEqual(self.validate().returncode, 0)
        self.assertNotIn("compile_status", self.values())

    def test_release_targets_actual_commit(self):
        result = self.run_step("Upload Kernel to Release", 'gh() { printf "%s\\n" "$@" > "$TRACE"; }')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        args = self.trace.read_text().splitlines()
        self.assertIn("--target", args)
        self.assertEqual(args[args.index("--target") + 1], "c" * 40)

    def test_pruning_requires_successful_publication(self):
        condition = self.steps["Prune old releases"]["if"]
        release_id = self.steps["Upload Kernel to Release"].get("id")
        for outcome, cancelled, expected in (("failure", False, False), ("skipped", False, False),
                                              ("success", True, False), ("success", False, True)):
            with self.subTest(outcome=outcome, cancelled=cancelled):
                expression = condition.removeprefix("${{").removesuffix("}}")
                expression = expression.replace("env.UPLOAD_RELEASE", repr("true"))
                expression = expression.replace("env.compile_status", repr("success"))
                expression = re.sub(r"steps\.([A-Za-z0-9_-]+)\.outcome",
                                    lambda m: repr(outcome if m[1] == release_id else ""), expression)
                expression = expression.replace("cancelled()", repr(cancelled)).replace("&&", " and ").replace("!", " not ")
                tree = ast.parse(expression.strip(), mode="eval")
                allowed = (ast.Expression, ast.BoolOp, ast.And, ast.UnaryOp, ast.Not,
                           ast.Compare, ast.Eq, ast.Constant)
                self.assertTrue(all(isinstance(node, allowed) for node in ast.walk(tree)))
                # Interpret only literals, equality and boolean operators; never
                # execute source expressions or resolve names/calls from the YAML.
                def value(node):
                    if isinstance(node, ast.Expression):
                        return value(node.body)
                    if isinstance(node, ast.Constant):
                        return node.value
                    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
                        return all(value(item) for item in node.values)
                    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                        return not value(node.operand)
                    if isinstance(node, ast.Compare) and all(isinstance(op, ast.Eq) for op in node.ops):
                        values = [value(node.left)] + [value(item) for item in node.comparators]
                        return all(left == right for left, right in zip(values, values[1:]))
                    raise AssertionError("Unsupported workflow condition")
                self.assertEqual(value(tree), expected)


if __name__ == "__main__":
    unittest.main()
