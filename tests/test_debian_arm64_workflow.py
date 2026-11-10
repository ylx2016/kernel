"""Run ARM64 workflow shell with isolated CLI fixtures, never Docker/build/network.

The receiver sees real filesystem objects. The final verifier consumes real tar
streams and binary signatures; only dpkg-deb's unavailable CLI is modelled.
"""

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


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/Debian_kernel_arm64_latest.yml"
BASE_ID = "sha256:" + "a" * 64
VERSION = "7.3.3"
PACKAGES = ("linux-image-7.3.3", "linux-headers-7.3.3", "linux-libc-dev")
FILENAMES = tuple(name + "_7.3.3-2_arm64.deb" for name in PACKAGES)
IMAGE = "./boot/vmlinuz-7.3.3"
HEADER_ROOT = "./usr/src/linux-headers-7.3.3/"
ELF = b"\x7fELF\x02\x01\x01" + bytes(11) + b"\xb7\x00" + bytes(44)
RAW_IMAGE = bytes(56) + b"ARM\x64" + bytes(4)


class Arm64WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash, yq = shutil.which("bash"), shutil.which("yq")
        if cls.bash is None or yq is None:
            raise RuntimeError("bash and mikefarah/yq are required")
        cls.doc = json.loads(subprocess.run(
            [yq, "-o=json", ".", str(WORKFLOW)], check=True, capture_output=True,
            text=True, encoding="utf-8", timeout=15,
        ).stdout)
        cls.steps = {step["name"]: step for job in cls.doc["jobs"].values()
                     for step in job["steps"]}

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="arm64-workflow-test-")
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.workspace = self.work / "workspace"
        self.runner = self.work / "runner"
        self.workspace.mkdir()
        self.runner.mkdir()
        self.env_file = self.work / "github-env"
        self.env_file.touch()
        self.output_file = self.work / "github-output"
        self.output_file.touch()
        self.trace = self.work / "trace"
        self.env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR")
                    if key in os.environ}
        self.env.update(HOME=self.work.as_posix(), TMP=self.runner.as_posix(),
                        TEMP=self.runner.as_posix(), TMPDIR=self.runner.as_posix(),
                        LC_ALL="C.UTF-8", RUNNER_TEMP=self.runner.as_posix(),
                        GITHUB_WORKSPACE=self.workspace.as_posix(), GITHUB_SHA="c" * 40,
                        GITHUB_REPOSITORY="fixture/kernel", BUILD_BASE_IMAGE_ID=BASE_ID,
                        GITHUB_ENV=self.env_file.as_posix(), KERNEL_VER=VERSION,
                        GITHUB_OUTPUT=self.output_file.as_posix(),
                        BUILD_IMAGE="debian:12-slim", BUILD_CONTAINER="arm64-builder",
                        VERIFY_CONTAINER="arm64-verifier", BUILD_ARCH="linux/arm64",
                        RELEASE_TAG="arm64-release-fixture", TZ="Asia/Shanghai",
                        TEST_WORK=self.work.as_posix(), TRACE=self.trace.as_posix(),
                        TEST_PYTHON=Path(sys.executable).as_posix(),
                        RELEASE_PREFIX="Debian_Kernel_", ARM64_SUFFIX="latest_arm64_bbr_",
                        KEEP="3", FORCE_BUILD="false")

    def body(self, name):
        return self.steps[name]["run"]

    def run_shell(self, program, prefix=""):
        return subprocess.run(
            [self.bash, "--noprofile", "--norc"], input=prefix + "\n" + program,
            env=self.env, cwd=self.work, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )

    def values(self, path=None):
        return dict(line.split("=", 1) for line in
                    (path or self.env_file).read_text(encoding="utf-8").splitlines())

    def prepare_upload(self):
        upload = self.workspace / "upload"
        upload.mkdir()
        for filename in FILENAMES:
            (upload / filename).write_bytes(b"unverified deb fixture")
        return upload

    def collect(self):
        return self.run_shell(self.body("Collect deb artifacts"),
                              'python3() { "$TEST_PYTHON" "$@"; }')

    def assert_rejected_collection(self):
        result = self.collect()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("UPLOAD_PATH", self.values())
        self.assertFalse(any(path.is_file() for path in self.runner.rglob("*")),
                         "Validate the whole input set before copying any payload")

    def test_collect_creates_separate_snapshot_without_authorizing_release(self):
        self.prepare_upload()
        result = self.collect()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        destination = Path(self.values()["UPLOAD_PATH"])
        self.assertEqual(destination.parent, self.runner)
        self.assertEqual({p.name for p in destination.iterdir()}, set(FILENAMES))
        for path in destination.iterdir():
            self.assertEqual(path.read_bytes(), b"unverified deb fixture")
            self.assertEqual(path.stat().st_nlink, 1)
        self.assertNotIn("compile_status", self.values())

    def test_collect_rejects_wrong_architecture(self):
        upload = self.prepare_upload()
        (upload / FILENAMES[0]).rename(upload / FILENAMES[0].replace("arm64", "amd64"))
        self.assert_rejected_collection()

    def test_collect_rejects_wrong_package_version_name(self):
        upload = self.prepare_upload()
        (upload / FILENAMES[0]).rename(upload / "linux-image_7.3.3-2_arm64.deb")
        self.assert_rejected_collection()

    def test_collect_rejects_wrong_kernel_version(self):
        upload = self.prepare_upload()
        (upload / FILENAMES[0]).rename(upload / FILENAMES[0].replace("7.3.3", "7.3.2"))
        self.assert_rejected_collection()

    def test_collect_rejects_stray_and_hidden_files(self):
        upload = self.prepare_upload()
        (upload / ".unexpected").write_bytes(b"stray")
        self.assert_rejected_collection()

    def test_collect_rejects_extra_directory(self):
        (self.prepare_upload() / "extra").mkdir()
        self.assert_rejected_collection()

    def test_collect_rejects_empty_package(self):
        (self.prepare_upload() / FILENAMES[0]).write_bytes(b"")
        self.assert_rejected_collection()

    def test_collect_rejects_oversized_package(self):
        with (self.prepare_upload() / FILENAMES[0]).open("r+b") as stream:
            stream.truncate(2 * 1024**3)
        self.assert_rejected_collection()

    def test_collect_rejects_hardlink(self):
        upload = self.prepare_upload()
        os.link(upload / FILENAMES[0], self.work / "alias")
        self.assert_rejected_collection()

    def test_collect_rejects_symlink(self):
        upload = self.prepare_upload()
        target = self.work / "real-deb"
        (upload / FILENAMES[0]).rename(target)
        try:
            (upload / FILENAMES[0]).symlink_to(target)
        except OSError as error:
            self.skipTest(f"Symlink unavailable: {error}")
        self.assert_rejected_collection()

    def test_collect_rejects_symlinked_source_directory(self):
        upload = self.prepare_upload()
        real = self.work / "real-upload"
        upload.rename(real)
        try:
            upload.symlink_to(real, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Symlink unavailable: {error}")
        self.assert_rejected_collection()

    def test_collect_rejects_inconsistent_revisions(self):
        upload = self.prepare_upload()
        (upload / FILENAMES[0]).rename(upload / FILENAMES[0].replace("-2_", "-3_"))
        self.assert_rejected_collection()

    def prepare_verifier(self, metadata_change=None, payload_change=None):
        upload = self.prepare_upload()
        self.env["UPLOAD_PATH"] = upload.as_posix()
        fixtures = self.work / "cli-fixtures"
        fixtures.mkdir()
        self.env["FIXTURES"] = fixtures.as_posix()
        metadata = {filename: {"Package": package, "Version": "7.3.3-2", "Architecture": "arm64"}
                    for filename, package in zip(FILENAMES, PACKAGES)}
        if metadata_change:
            metadata_change(metadata)
        (fixtures / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        payloads = {
            FILENAMES[0]: [(IMAGE, RAW_IMAGE, None)],
            FILENAMES[1]: [(HEADER_ROOT + "Makefile", b"# headers\n", None),
                           (HEADER_ROOT + "scripts/basic/fixdep", ELF, None),
                           (HEADER_ROOT + "scripts/mod/modpost", ELF, None)],
            FILENAMES[2]: [("./usr/include/linux/types.h", b"/* types */\n", None)],
        }
        if payload_change:
            payload_change(payloads)
        for filename, members in payloads.items():
            with tarfile.open(fixtures / (filename + ".tar"), "w") as archive:
                for name, data, link in members:
                    entry = tarfile.TarInfo(name)
                    if link:
                        entry.type, entry.linkname = tarfile.SYMTYPE, link
                        archive.addfile(entry)
                    else:
                        entry.size = len(data)
                        entry.mode = 0o644
                        archive.addfile(entry, io.BytesIO(data))
        cli = self.work / "dpkg_fixture.py"
        cli.write_text('''import json, os, pathlib, sys
root = pathlib.Path(os.environ["FIXTURES"])
args = sys.argv[1:]
if args[0] == "-f":
    values = json.loads((root / "metadata.json").read_text())[pathlib.Path(args[1]).name]
    fields = args[2:]
    for field in fields:
        print((field + ": " if len(fields) > 1 else "") + values[field])
elif args[0] == "--fsys-tarfile":
    sys.stdout.buffer.write((root / (pathlib.Path(args[1]).name + ".tar")).read_bytes())
else:
    raise SystemExit("Unexpected dpkg-deb call: " + repr(args))
''', encoding="utf-8")
        self.env["TEST_CLI"] = cli.as_posix()
        # Only replace container paths and the unavailable native deb CLI.
        # tar/stat/od/dd and the complete VERIFY program are real processes.
        self.env["VERIFIER_PREFIX"] = r'''
cd() { if [ "$1" = /packages ]; then builtin cd "$UPLOAD_PATH"; else builtin cd "$@"; fi; }
dpkg-deb() { "$TEST_PYTHON" -I -B "$TEST_CLI" "$@"; }
'''
        if os.name == "nt":
            # Git Bash has no RLIMIT_FSIZE support. Keep the Linux production
            # guard; only model this OS boundary, not any validation logic.
            self.env["VERIFIER_PREFIX"] += '\nulimit() { [ "$*" = "-f 196608" ]; }\n'

    def validate(self):
        return self.run_shell(self.body("Validate final deb artifacts"), r'''
docker() {
    printf '%s\n' "$@" > "$TRACE"
    { printf '%s\n' "$VERIFIER_PREFIX"; command cat; } | command bash --noprofile --norc
}
''')

    def assert_rejected_validation(self):
        result = self.validate()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("compile_status", self.values())

    def test_real_verifier_accepts_debian_metadata_tar_paths_and_arm_signatures(self):
        self.prepare_verifier()
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.values().get("compile_status"), "success")
        args = self.trace.read_text().splitlines()
        self.assertIn(BASE_ID, args)
        self.assertNotIn("debian:12-slim", args)
        self.assertIn("--read-only", args)
        self.assertEqual(args[args.index("--name") + 1], "arm64-verifier")
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertEqual(args[args.index("--platform") + 1], "linux/arm64")
        self.assertNotEqual(args[args.index("--user") + 1].split(":")[0], "0")
        self.assertIn("type=bind,source=" + self.env["UPLOAD_PATH"] + ",target=/packages,readonly", args)
        self.assertNotIn("TOKEN", " ".join(args))

    def test_verifier_rejects_metadata_arch_despite_arm64_filename(self):
        self.prepare_verifier(lambda m: m[FILENAMES[0]].update(Architecture="amd64"))
        self.assert_rejected_validation()

    def test_verifier_rejects_metadata_name_despite_valid_filename(self):
        self.prepare_verifier(lambda m: m[FILENAMES[0]].update(Package="linux-image"))
        self.assert_rejected_validation()

    def test_verifier_rejects_metadata_version_despite_valid_filename(self):
        self.prepare_verifier(lambda m: m[FILENAMES[0]].update(Version="7.3.3-3"))
        self.assert_rejected_validation()

    def test_verifier_rejects_header_helper_x86_elf(self):
        def change(payloads):
            payloads[FILENAMES[1]][1] = (HEADER_ROOT + "scripts/basic/fixdep",
                                        ELF[:18] + b"\x3e\x00" + ELF[20:], None)
        self.prepare_verifier(payload_change=change)
        self.assert_rejected_validation()

    def test_verifier_rejects_modpost_wrong_class_or_endianness(self):
        def change(payloads):
            payloads[FILENAMES[1]][2] = (HEADER_ROOT + "scripts/mod/modpost",
                                        ELF[:4] + b"\x01\x02" + ELF[6:], None)
        self.prepare_verifier(payload_change=change)
        self.assert_rejected_validation()

    def test_verifier_rejects_non_elf_helper(self):
        def change(payloads):
            payloads[FILENAMES[1]][1] = (HEADER_ROOT + "scripts/basic/fixdep", b"#!/bin/sh\n", None)
        self.prepare_verifier(payload_change=change)
        self.assert_rejected_validation()

    def test_verifier_rejects_elf_instead_of_raw_image(self):
        self.prepare_verifier(payload_change=lambda p: p[FILENAMES[0]].__setitem__(0, (IMAGE, ELF, None)))
        self.assert_rejected_validation()

    def test_verifier_rejects_wrong_image_magic(self):
        self.prepare_verifier(payload_change=lambda p: p[FILENAMES[0]].__setitem__(0, (IMAGE, bytes(64), None)))
        self.assert_rejected_validation()

    def test_verifier_rejects_symlink_payload(self):
        self.prepare_verifier(payload_change=lambda p: p[FILENAMES[0]].__setitem__(0, (IMAGE, b"", "/etc/passwd")))
        self.assert_rejected_validation()

    def test_verifier_rejects_duplicate_image_member(self):
        self.prepare_verifier(payload_change=lambda p: p[FILENAMES[0]].append((IMAGE, RAW_IMAGE, None)))
        self.assert_rejected_validation()

    def test_verifier_rejects_missing_modpost(self):
        self.prepare_verifier(payload_change=lambda p: p[FILENAMES[1]].pop())
        self.assert_rejected_validation()

    def test_failed_docker_validation_blocks_release(self):
        self.env["UPLOAD_PATH"] = self.prepare_upload().as_posix()
        result = self.run_shell(self.body("Validate final deb artifacts"),
                                'docker() { command cat > "$TRACE"; return 17; }')
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        self.assertNotIn("compile_status", self.values())

    def test_release_targets_built_commit(self):
        self.env["UPLOAD_PATH"] = self.prepare_upload().as_posix()
        result = self.run_shell(self.body("Upload Kernel to Release"),
                                'gh() { printf "%s\\n" "$@" > "$TRACE"; }')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        args = self.trace.read_text().splitlines()
        self.assertEqual(args[args.index("--target") + 1], "c" * 40)
        self.assertEqual(sum(arg.endswith(".deb") for arg in args), 3)

    def check_update(self, tags, fail=False):
        self.env["RELEASES"] = tags
        self.env["GH_FAIL"] = "1" if fail else "0"
        return self.run_shell(self.body("Check latest kernel version"), r'''
git() { printf 'hash\trefs/tags/v7.3.3\nhash\trefs/tags/v7.4-rc1\n'; }
gh() {
    printf '%s\n' "$@" > "$TRACE"
    [ "$GH_FAIL" = 0 ] || return 19
    printf '%s\n' "$RELEASES"
}
''')

    def test_check_update_deduplicates_only_exact_arm_namespace(self):
        tag = "Debian_Kernel_7.3.3_latest_arm64_bbr_2026.11.10-0100"
        result = self.check_update(tag)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.values(self.output_file)["build_needed"], "false")
        self.assertIn("--exclude-drafts", self.trace.read_text().splitlines())

    def test_check_update_does_not_match_lookalike_or_x86_tags(self):
        result = self.check_update("\n".join((
            "Debian_Kernel_Cloud_7.3.3_bbr_2026.11.10-0100",
            "archive_Debian_Kernel_7.3.3_latest_arm64_bbr_2026.11.10-0100",
            "Debian_Kernel_7.3.3_latest_arm64_other_2026.11.10-0100",
            "Debian_Kernel_7.3.30_latest_arm64_bbr_2026.11.10-0100")))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.values(self.output_file)["build_needed"], "true")

    def test_check_update_release_query_failure_is_closed_even_when_forced(self):
        self.env["FORCE_BUILD"] = "true"
        result = self.check_update("", fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("build_needed", self.values(self.output_file))

    def test_check_update_force_rebuild(self):
        self.env["FORCE_BUILD"] = "true"
        result = self.check_update("Debian_Kernel_7.3.3_latest_arm64_bbr_2026.11.10-0100")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.values(self.output_file)["build_needed"], "true")

    def test_prune_deletes_only_old_exact_arm_tags(self):
        tags = [f"Debian_Kernel_7.3.{i}_latest_arm64_bbr_2026.11.0{i}-0100" for i in range(1, 5)]
        others = ["Debian_Kernel_Cloud_7.3.0_bbr_2026.01.01-0100",
                  "Centos_Kernel_Cloud_7.3.0_bbr_2026.01.01-0100",
                  "Debian_Kernel_7.3.0_latest_arm64_bbr_not-a-timestamp",
                  "Debian_Kernel_7.3.0_latest_arm64_bbr_2026.01.01-0100_extra"]
        self.env["RELEASES"] = "\n".join(f"2026-11-{i:02}T00:00:00Z\t{tag}"
                                         for i, tag in enumerate(tags + others, 1))
        result = self.run_shell(self.body("Prune old releases"), r'''
gh() {
    case "$1 $2" in
      'release list') printf '%s\n' "$RELEASES" ;;
      'release delete') printf '%s\n' "$3" >> "$TRACE" ;;
      *) return 99 ;;
    esac
}
sleep() { :; }
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.trace.read_text().splitlines(), [tags[0]])

    def start_container(self, host="aarch64", container="aarch64", debian="arm64"):
        self.env.update(HOST_ARCH=host, CONTAINER_ARCH=container, DEBIAN_ARCH=debian)
        return self.run_shell(self.body("Start Debian 12 ARM64 build container"), r'''
uname() { printf '%s\n' "$HOST_ARCH"; }
docker() {
    case "$1 $2" in
      'pull --platform'|'rm -f') return 0 ;;
      'image inspect') printf '%s\n' "$BUILD_BASE_IMAGE_ID" ;;
      'run -d') printf '%s\n' "$@" > "$TRACE" ;;
      'exec arm64-builder')
        case "$3" in
          cat) printf '12.12\n' ;;
          uname) printf '%s\n' "$CONTAINER_ARCH" ;;
          dpkg) printf '%s\n' "$DEBIAN_ARCH" ;;
          *) return 98 ;;
        esac ;;
      *) return 99 ;;
    esac
}
df() { :; }
''')

    def test_native_arm_builder_uses_recorded_image(self):
        result = self.start_container()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.values()["BUILD_BASE_IMAGE_ID"], BASE_ID)
        self.assertIn(BASE_ID, self.trace.read_text().splitlines())

    def test_rejects_x86_host(self):
        result = self.start_container(host="x86_64")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists(), "Wrong host must not start builder")

    def test_rejects_wrong_container_architecture(self):
        result = self.start_container(container="x86_64")
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_wrong_debian_architecture(self):
        result = self.start_container(debian="amd64")
        self.assertNotEqual(result.returncode, 0)

    def docker_exec_program(self, name):
        match = re.search(r"bash -c '\n(.*?)\n[ \t]*'(?:\n|$)", self.body(name), re.S)
        self.assertIsNotNone(match, "Missing docker exec shell")
        return match.group(1)

    def test_dependency_step_rejects_x86_gcc_target(self):
        program = self.docker_exec_program("Install Dependencies (Debian 12 ARM64)")
        self.env.update(HOST_UID="1001", HOST_GID="1001")
        result = self.run_shell(program, r'''
apt-get() { :; }
rm() { :; }
groupadd() { :; }
useradd() { :; }
id() { printf '1001\n'; }
gcc() { if [ "$1" = -dumpmachine ]; then printf 'x86_64-linux-gnu\n'; else printf 'gcc fixture\n'; fi; }
ld() { printf 'ld fixture\n'; }
make() { printf 'make fixture\n'; }
dpkg-query() { :; }
''')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_compile_requests_raw_image_modules_dtbs_and_arm64_debs(self):
        program = self.docker_exec_program("Compile Kernel")
        result = self.run_shell(program, r'''
cd() { builtin cd "$TEST_WORK"; }
nproc() { printf '4\n'; }
make() {
    printf '%s\n' "$*" >> "$TRACE"
    case " $* " in *' bindeb-pkg '*) return 42 ;; esac
}
''')
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        calls = self.trace.read_text().splitlines()
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertIn("ARCH=arm64", call.split())
            self.assertIn("KBUILD_IMAGE=arch/arm64/boot/Image", call.split())
        for target in ("Image", "modules", "dtbs"):
            self.assertIn(target, calls[0].split())
        self.assertIn("KBUILD_DEBARCH=arm64", calls[1].split())

    def test_cleanup_removes_both_containers(self):
        result = self.run_shell(self.body("Stop build container"),
                                'docker() { printf "%s\\n" "$@" > "$TRACE"; }')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.trace.read_text().splitlines(), ["rm", "-f", "arm64-builder", "arm64-verifier"])


if __name__ == "__main__":
    unittest.main()
