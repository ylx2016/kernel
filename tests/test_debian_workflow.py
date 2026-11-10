"""Exercise the actual check_update shell with local git/gh fixtures.

No GitHub credentials or network calls are used. The draft-only case must
request a build; removing --exclude-drafts reproduces the skipped-build bug.
Run: python -I -B -m unittest discover -s tests -p 'test_*.py' -v
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/Debian_kernel_latest.yml"
BASH = shutil.which("bash")
YQ = shutil.which("yq")
FIXTURES = r"""
git() {
    if [ "$1" != ls-remote ]; then return 99; fi
    printf '%s\t%s\n' 0123456789012345678901234567890123456789 refs/tags/v6.12.42
}
gh() {
    if [ "$1 $2" != 'release list' ]; then return 99; fi
    case "$FIXTURE_RELEASE" in
        error) return 1 ;;
        none) return 0 ;;
        draft)
            for arg in "$@"; do
                if [ "$arg" = --exclude-drafts ]; then return 0; fi
            done
            ;;
        published) ;;
        *) return 99 ;;
    esac
    printf '%s\n' Debian_Kernel_Cloud_6.12.42_bbr_2026.11.10-1200
}
"""


class ReleaseDedupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if BASH is None or YQ is None:
            raise RuntimeError("bash and mikefarah/yq are required")
        cls.check_script = subprocess.run(
            [YQ, "-r", ".jobs.check_update.steps[0].run", str(WORKFLOW)],
            check=True, capture_output=True, text=True, encoding="utf-8", timeout=15,
        ).stdout

    def run_check(self, release, force=False):
        with tempfile.TemporaryDirectory(prefix="kernel-release-test-") as directory:
            work = Path(directory)
            output = work / "github-output"
            output.touch()
            env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR")
                   if key in os.environ}
            env.update(HOME=work.as_posix(), TMP=work.as_posix(),
                       TEMP=work.as_posix(), TMPDIR=work.as_posix(), LC_ALL="C.UTF-8",
                       GITHUB_OUTPUT=output.as_posix(), GITHUB_REPOSITORY="fixture/kernel",
                       FORCE_BUILD="true" if force else "false", FIXTURE_RELEASE=release)
            result = subprocess.run(
                [BASH, "--noprofile", "--norc"], input=FIXTURES + self.check_script,
                cwd=work, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15,
            )
            values = dict(line.split("=", 1) for line in output.read_text().splitlines())
            return result, values

    def test_build_decision(self):
        cases = (("draft", False, "true"), ("published", False, "false"),
                 ("none", False, "true"), ("published", True, "true"),
                 ("draft", True, "true"))
        for release, force, expected in cases:
            with self.subTest(release=release, force=force):
                result, values = self.run_check(release, force)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(values.get("kernel_ver"), "6.12.42")
                self.assertEqual(values.get("build_needed"), expected, result.stdout)

    def test_failed_release_lookup_never_starts_build(self):
        result, values = self.run_check("error")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("build_needed", values)


if __name__ == "__main__":
    unittest.main()
