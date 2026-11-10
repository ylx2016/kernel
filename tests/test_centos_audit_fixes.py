"""Run actual workflow shell with local boundary fixtures, never Docker or GitHub.

These regressions cover fail-closed gates and the verifier invocation contract.
They do not reproduce an exploit or establish real RPM/EL8 compatibility.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/Centos_kernel_latest.yml"
BASE_ID = "sha256:" + "b" * 64
COMMIT = "a" * 40


class CentosAuditFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        yq = shutil.which("yq")
        if not cls.bash or not yq:
            raise RuntimeError("bash and mikefarah/yq are required")
        doc = json.loads(subprocess.run(
            [yq, "-o=json", ".", str(WORKFLOW)], check=True, capture_output=True,
            text=True, encoding="utf-8", timeout=15,
        ).stdout)
        cls.steps = {step["name"]: step for step in doc["jobs"]["build"]["steps"]}

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="centos-audit-test-")
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.env_file = self.work / "github-env"
        self.env_file.touch()
        self.trace = self.work / "trace"
        self.env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR")
                    if key in os.environ}
        self.env.update(HOME=self.work.as_posix(), TMP=self.work.as_posix(),
                        TEMP=self.work.as_posix(), TMPDIR=self.work.as_posix(), LC_ALL="C.UTF-8",
                        RUNNER_TEMP=self.work.as_posix(), GITHUB_WORKSPACE=self.work.as_posix(),
                        GITHUB_ENV=self.env_file.as_posix(), GITHUB_REPOSITORY="fixture/kernel",
                        GITHUB_SHA=COMMIT, KERNEL_VER="7.3.3", RELEASE_TAG="fixture-release",
                        BUILD_IMAGE="almalinux:8", BUILD_CONTAINER="fixture-builder",
                        VERIFY_CONTAINER="fixture-verifier",
                        BUILD_BASE_IMAGE_ID=BASE_ID, TZ="Asia/Shanghai", FETCH_METHOD="auto",
                        TEST_WORK=self.work.as_posix(), TRACE=self.trace.as_posix(),
                        TEST_PYTHON=Path(sys.executable).as_posix())

    def body(self, name):
        self.assertIn(name, self.steps, f"Missing workflow step: {name}")
        return self.steps[name]["run"]

    def inner(self, name, delimiter):
        match = re.search(r"<<'" + delimiter + r"'\n(.*?)\n" + delimiter + r"(?:\n|$)",
                          self.body(name), re.S)
        self.assertIsNotNone(match, f"Missing {delimiter} program")
        return match.group(1)

    def run_shell(self, program, prefix=""):
        return subprocess.run(
            [self.bash, "--noprofile", "--norc"], input=prefix + "\n" + program,
            env=self.env, cwd=self.work, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        )

    def values(self):
        return dict(line.split("=", 1) for line in self.env_file.read_text().splitlines())

    def prepare_packages(self):
        directory = self.work / "rpm-output" / "x86_64"
        directory.mkdir(parents=True)
        for name in ("kernel", "kernel-devel", "kernel-headers"):
            (directory / f"{name}-7.3.3-2.el8.x86_64.rpm").write_bytes(b"unverified fixture")

    def collect(self):
        self.prepare_packages()
        result = self.run_shell(self.body("Collect RPM artifacts"),
                                'python3() { "$TEST_PYTHON" "$@"; }')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.env["UPLOAD_PATH"] = self.values()["UPLOAD_PATH"]

    def test_existing_source_stops_before_fetch(self):
        (self.work / "linux-7.3.3").mkdir()
        result = self.run_shell(self.inner("Get Kernel Version & Source", "SOURCE"), r'''
cd() { builtin cd "$TEST_WORK"; }
aria2c() { printf 'aria2c\n' >> "$TRACE"; return 1; }
git() { printf 'git\n' >> "$TRACE"; return 1; }
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists(), "Existing source must not reach a downloader")

    def test_old_python_stops_before_make(self):
        program = self.inner("Configure Kernel (CentOS/RHEL Cloud & Panel Optimized)", "CONFIGURE")
        result = self.run_shell(program, r'''
source() { return 0; }
gcc() { printf '12\n'; }
python3() {
    "$TEST_PYTHON" -I -c 'import sys; sys.version_info=(3,6,8); exec(sys.argv[-1])' "$@"
}
cd() { builtin cd "$TEST_WORK"; }
make() { printf 'make\n' >> "$TRACE"; return 42; }
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists(), "Python 3.6 must not reach make")

    def test_python_39_reaches_make(self):
        program = self.inner("Configure Kernel (CentOS/RHEL Cloud & Panel Optimized)", "CONFIGURE")
        result = self.run_shell(program, r'''
source() { return 0; }
gcc() { printf '12\n'; }
python3() {
    "$TEST_PYTHON" -I -c 'import sys; sys.version_info=(3,9,20); exec(sys.argv[-1])' "$@"
}
cd() { builtin cd "$TEST_WORK"; }
make() { printf 'make\n' >> "$TRACE"; return 42; }
''')
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        self.assertEqual(self.trace.read_text(), "make\n")

    def test_collection_alone_does_not_authorize_release(self):
        self.collect()
        self.assertNotIn("compile_status", self.values(),
                         "A path-safe copy is not yet a validated RPM set")

    def test_failed_final_validation_blocks_release(self):
        self.collect()
        result = self.run_shell(self.body("Validate final RPM artifacts"), r'''
docker() { command cat > "$TRACE"; return 17; }
''')
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        self.assertNotIn("compile_status", self.values())

    def test_final_verifier_uses_immutable_base_and_readonly_snapshot(self):
        self.collect()
        result = self.run_shell(self.body("Validate final RPM artifacts"), r'''
docker() { printf '%s\n' "$@" > "$TRACE"; command cat > /dev/null; }
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.values().get("compile_status"), "success")
        args = self.trace.read_text().splitlines()
        self.assertIn(BASE_ID, args)
        self.assertNotIn("almalinux:8", args)
        self.assertIn("--read-only", args)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertIn("type=bind,source=" + self.env["UPLOAD_PATH"] + ",target=/packages,readonly", args)
        self.assertNotIn("GH_TOKEN", " ".join(args))

    def test_release_targets_built_commit(self):
        self.env["UPLOAD_PATH"] = self.work.as_posix()
        result = self.run_shell(self.body("Upload Kernel to Release"),
                                'gh() { printf "%s\\n" "$@" > "$TRACE"; }')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        args = self.trace.read_text().splitlines()
        self.assertIn("--target", args)
        self.assertEqual(args[args.index("--target") + 1], COMMIT)

    def test_builder_and_verifier_share_recorded_base_id(self):
        result = self.run_shell(self.body("Start AlmaLinux 8 build container"), r'''
docker() {
    case "$1 $2" in
        'pull almalinux:8') return 0 ;;
        'image inspect') printf '%s\n' "$BUILD_BASE_IMAGE_ID" ;;
        'run -d') printf '%s\n' "$@" > "$TRACE" ;;
        *) return 99 ;;
    esac
}
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.values().get("BUILD_BASE_IMAGE_ID"), BASE_ID)
        self.assertIn(BASE_ID, self.trace.read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
