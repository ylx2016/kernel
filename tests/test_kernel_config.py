"""Regression tests for the real common-config verifier (no kernel build).

Run: python -I -m unittest discover -s tests -p 'test_*.py' -v
The hand-written fixture represents an olddefconfig result. Removing the
statistic critical check must make the disabled/missing-symbol cases fail.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "kernel-config-common.sh"
BASH = shutil.which("bash")
BASE_CONFIG = """\
CONFIG_EXT4_FS=y
CONFIG_VIRTIO_BLK=y
CONFIG_VIRTIO_NET=y
CONFIG_VIRTIO_PCI=y
CONFIG_SCSI_VIRTIO=y
CONFIG_BLK_DEV_NVME=y
CONFIG_SERIAL_8250_CONSOLE=y
CONFIG_TCP_CONG_BBR=y
CONFIG_NET_SCH_FQ=y
CONFIG_DEFAULT_TCP_CONG="bbr"
CONFIG_DEFAULT_NET_SCH="fq"
CONFIG_TUN=y
CONFIG_IPV6=y
CONFIG_NF_TABLES=y
CONFIG_IP_NF_IPTABLES=y
CONFIG_NETFILTER_XT_TARGET_MASQUERADE=y
CONFIG_OVERLAY_FS=y
CONFIG_NAMESPACES=y
CONFIG_CGROUPS=y
CONFIG_BRIDGE=y
CONFIG_VETH=y
CONFIG_SECCOMP=y
CONFIG_DEBUG_INFO_NONE=y
CONFIG_MODULE_COMPRESS_XZ=y
CONFIG_SECURITY_APPARMOR=y
CONFIG_SECURITY_SELINUX=y
CONFIG_LSM="landlock,lockdown,yama,loadpin,safesetid,integrity,apparmor,bpf"
"""
SYMBOL = "CONFIG_NETFILTER_XT_MATCH_STATISTIC"


class StatisticVerifierTests(unittest.TestCase):
    def verify(self, distro, extra):
        self.assertIsNotNone(BASH, "bash is required for the real verifier")
        with tempfile.TemporaryDirectory(prefix="kernel-config-test-") as directory:
            work = Path(directory)
            (work / ".config").write_text(BASE_CONFIG + extra, encoding="utf-8")
            env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR")
                   if key in os.environ}
            env.update(HOME=work.as_posix(), TMP=work.as_posix(),
                       TEMP=work.as_posix(), TMPDIR=work.as_posix(), LC_ALL="C.UTF-8")
            return subprocess.run(
                [BASH, "--noprofile", "--norc", SCRIPT.as_posix(), "verify", distro],
                cwd=work, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15,
            )

    def test_enabled_matcher_accepts_both_distros(self):
        for distro in ("debian", "centos"):
            for value in ("y", "m"):
                with self.subTest(distro=distro, value=value):
                    result = self.verify(distro, f"{SYMBOL}={value}\n")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_disabled_or_missing_matcher_rejects_both_distros(self):
        for distro in ("debian", "centos"):
            for extra in ("", f"# {SYMBOL} is not set\n", f"{SYMBOL}=n\n"):
                with self.subTest(distro=distro, config=extra):
                    result = self.verify(distro, extra)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    failures = [line for line in result.stdout.splitlines()
                                if "[FAIL]" in line]
                    self.assertTrue(any(SYMBOL in line for line in failures),
                                    result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
