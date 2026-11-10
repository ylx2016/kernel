"""Exercise the real shared verifier with ARM64 olddefconfig-result fixtures."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_kernel_config


ARM_KEYS = (
    "CONFIG_ARM64", "CONFIG_ARM64_4K_PAGES", "CONFIG_EFI", "CONFIG_EFI_STUB",
    "CONFIG_ACPI", "CONFIG_PCI", "CONFIG_PCI_HOST_GENERIC", "CONFIG_VIRTIO_MMIO",
    "CONFIG_SERIAL_AMBA_PL011", "CONFIG_SERIAL_AMBA_PL011_CONSOLE",
    "CONFIG_ARM_GIC_V3", "CONFIG_ARM_GIC_V3_ITS", "CONFIG_ARM_ARCH_TIMER", "CONFIG_ARM_PSCI_FW",
    "CONFIG_IOMMU_SUPPORT", "CONFIG_ARM_SMMU", "CONFIG_ARM_SMMU_V3",
    "CONFIG_TCP_CONG_ADVANCED", "CONFIG_NET_VENDOR_GOOGLE", "CONFIG_GVE",
)
BASE = test_kernel_config.BASE_CONFIG + "CONFIG_NETFILTER_XT_MATCH_STATISTIC=y\n"
SCRIPT = Path(__file__).resolve().parents[1] / "kernel-config-common.sh"


class Arm64ConfigTests(unittest.TestCase):
    def verify(self, config, profile="arm64"):
        with tempfile.TemporaryDirectory(prefix="arm64-config-test-") as directory:
            work = Path(directory)
            (work / ".config").write_text(config, encoding="utf-8")
            env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR")
                   if key in os.environ}
            env.update(HOME=work.as_posix(), TMP=work.as_posix(), TEMP=work.as_posix())
            return subprocess.run(
                [shutil.which("bash"), "--noprofile", "--norc", SCRIPT.as_posix(),
                 "verify", "debian", profile], cwd=work, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            )

    def test_complete_arm64_profile_passes(self):
        config = BASE + "".join(key + "=y\n" for key in ARM_KEYS)
        result = self.verify(config)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_or_modular_boot_requirement_fails(self):
        for missing in ARM_KEYS:
            with self.subTest(key=missing):
                config = BASE + "".join(key + "=y\n" for key in ARM_KEYS if key != missing)
                result = self.verify(config)
                self.assertEqual(result.returncode, 1, f"Missing {missing} was not rejected")
                self.assertTrue(any("[FAIL]" in line and missing in line
                                    for line in result.stdout.splitlines()), result.stdout)
        for required in ("CONFIG_VIRTIO_MMIO", "CONFIG_TCP_CONG_ADVANCED",
                         "CONFIG_NET_VENDOR_GOOGLE", "CONFIG_GVE"):
            for value in ("m", "n"):
                with self.subTest(key=required, value=value):
                    config = BASE + "".join(key + ("=" + value + "\n" if key == required else "=y\n")
                                           for key in ARM_KEYS)
                    result = self.verify(config)
                    self.assertEqual(result.returncode, 1, f"{required}={value} was not rejected")
                    self.assertTrue(any("[FAIL]" in line and required in line
                                        for line in result.stdout.splitlines()), result.stdout)

    def test_unknown_profile_is_rejected(self):
        self.assertEqual(self.verify(BASE, "typo-arm64").returncode, 1)

    def test_arm64_btf_or_dwarf_debug_info_fails(self):
        config = BASE + "".join(key + "=y\n" for key in ARM_KEYS)
        for key in ("CONFIG_DEBUG_INFO_BTF", "CONFIG_DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT",
                    "CONFIG_DEBUG_INFO_DWARF4", "CONFIG_DEBUG_INFO_DWARF5"):
            with self.subTest(key=key):
                self.assertEqual(self.verify(config + key + "=y\n").returncode, 1)

    def apply(self, profile, config):
        with tempfile.TemporaryDirectory(prefix="arm64-apply-test-") as directory:
            work = Path(directory)
            (work / ".config").write_text(config, encoding="utf-8")
            (work / "scripts").mkdir()
            command = work / "scripts/config"
            command.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$TRACE"\n',
                               encoding="utf-8", newline="\n")
            command.chmod(0o755)
            trace = work / "trace"
            env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR")
                   if key in os.environ}
            env.update(HOME=work.as_posix(), TRACE=trace.as_posix(), LC_ALL="C.UTF-8")
            args = [shutil.which("bash"), "--noprofile", "--norc", SCRIPT.as_posix(), "apply"]
            if profile:
                args.append(profile)
            result = subprocess.run(args, cwd=work, env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=30)
            calls = trace.read_text().splitlines() if trace.exists() else []
            return result, calls

    def test_arm64_apply_requests_boot_flags_and_disables_other_page_sizes(self):
        result, calls = self.apply("arm64", "CONFIG_ARM64=y\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for key in ARM_KEYS[1:]:
            with self.subTest(key=key):
                self.assertTrue("--enable " + key in calls, f"Apply did not enable {key}")
        for key in ("CONFIG_ARM64_16K_PAGES", "CONFIG_ARM64_64K_PAGES",
                    "CONFIG_DEBUG_INFO_BTF", "CONFIG_DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT",
                    "CONFIG_DEBUG_INFO_DWARF4", "CONFIG_DEBUG_INFO_DWARF5"):
            self.assertIn("--disable " + key, calls)
        self.assertIn("--enable CONFIG_DEBUG_INFO_NONE", calls)
        self.assertIn("--enable CONFIG_NETFILTER_XT_MATCH_STATISTIC", calls)
        self.assertNotIn("--enable CONFIG_CRYPTO_AES_NI_INTEL", calls)
        self.assertNotIn("--enable CONFIG_KVM_INTEL", calls)
        self.assertNotIn("--enable CONFIG_INTEL_IOMMU", calls)
        for parent, child in (("CONFIG_TCP_CONG_ADVANCED", "CONFIG_TCP_CONG_BBR"),
                              ("CONFIG_TCP_CONG_ADVANCED", "CONFIG_DEFAULT_BBR"),
                              ("CONFIG_NET_VENDOR_GOOGLE", "CONFIG_GVE")):
            with self.subTest(parent=parent, child=child):
                enable_parent, enable_child = "--enable " + parent, "--enable " + child
                self.assertTrue(enable_parent in calls and enable_child in calls
                                and calls.index(enable_parent) < calls.index(enable_child),
                                f"{parent} must be enabled before {child}")

    def test_arm64_apply_rejects_x86_config_before_any_change(self):
        result, calls = self.apply("arm64", "CONFIG_X86_64=y\n")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, [])

    def test_default_apply_keeps_x86_acceleration_and_has_no_arm_requests(self):
        result, calls = self.apply(None, "CONFIG_X86_64=y\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--enable CONFIG_CRYPTO_AES_NI_INTEL", calls)
        self.assertIn("--enable CONFIG_KVM_INTEL", calls)
        self.assertNotIn("--enable CONFIG_ARM_SMMU", calls)
        self.assertNotIn("--enable CONFIG_TCP_CONG_ADVANCED", calls)
        self.assertNotIn("--enable CONFIG_NET_VENDOR_GOOGLE", calls)


if __name__ == "__main__":
    unittest.main()
