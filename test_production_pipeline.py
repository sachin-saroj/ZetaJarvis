#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: test_production_pipeline.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Comprehensive unit and integration test suite for production
#              deployment sub-systems: env_validator, governor, log_rotator,
#              installer, and build packaging helpers.
# ------------------------------------------------------------------------------

"""Unit & Integration Test Suite for Production Deployment Pipeline."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*Setting the shape on a NumPy array.*")

WORKSPACE_ROOT = Path(__file__).resolve().parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import brain
from build import (
    generate_icon_if_missing,
    generate_version_info_file,
    read_version,
)
from env_validator import DiagnosticReport, EnvironmentValidator
from governor import (
    CPU_HIGH_THRESHOLD,
    CPU_LOW_THRESHOLD,
    EMERGENCY_CPU_THRESHOLD,
    EMERGENCY_DURATION_SEC,
    RAM_HIGH_THRESHOLD,
    RAM_LOW_THRESHOLD,
    ResourceGovernor,
)
from installer import (
    ZetaInstaller,
    get_default_install_dir,
    is_admin,
    parse_args,
)
from log_rotator import LogRotator


class TestEnvironmentValidator(unittest.TestCase):
    """Tests for Sub-system B: env_validator.py."""

    def setUp(self) -> None:
        self.validator = EnvironmentValidator()

    def test_validate_microphone_safe(self) -> None:
        ok, msg = self.validator.validate_microphone()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(msg, str)

    def test_validate_connectivity_fallback(self) -> None:
        # Test probing an unreachable offline local endpoint with retries
        bad_validator = EnvironmentValidator(endpoint_url="http://127.0.0.1:59999")
        ok, msg = bad_validator.validate_connectivity(retries=1)
        self.assertFalse(ok)
        self.assertIn("unreachable", msg.lower())

    def test_validate_api_key_detection(self) -> None:
        # Clear env variables temporarily
        old_jarvis_key = os.environ.get("JARVIS_API_KEY")
        old_or_key = os.environ.get("OPENROUTER_API_KEY")

        try:
            os.environ["JARVIS_API_KEY"] = "test-sk-1234567890abcdef"
            ok, msg = self.validator.validate_api_key()
            self.assertTrue(ok)

            os.environ["JARVIS_API_KEY"] = "your-openrouter-key-here"
            os.environ["OPENROUTER_API_KEY"] = ""
            ok, msg = self.validator.validate_api_key()
            self.assertFalse(ok)
        finally:
            if old_jarvis_key is not None:
                os.environ["JARVIS_API_KEY"] = old_jarvis_key
            else:
                os.environ.pop("JARVIS_API_KEY", None)
            if old_or_key is not None:
                os.environ["OPENROUTER_API_KEY"] = old_or_key
            else:
                os.environ.pop("OPENROUTER_API_KEY", None)

    def test_validate_dependencies(self) -> None:
        ok, msg = self.validator.validate_dependencies(auto_install=False)
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(msg, str)

    def test_run_diagnostics_report(self) -> None:
        report = self.validator.run_diagnostics(speak_warnings=False)
        self.assertIsInstance(report, DiagnosticReport)
        self.assertIn("Startup Environment Status", report.summary())


class TestResourceGovernor(unittest.TestCase):
    """Tests for Sub-system C: governor.py."""

    def test_get_system_metrics(self) -> None:
        gov = ResourceGovernor()
        cpu, ram = gov.get_system_metrics()
        self.assertIsInstance(cpu, float)
        self.assertIsInstance(ram, float)
        self.assertGreaterEqual(ram, 0.0)

    def test_governor_throttle_and_recovery(self) -> None:
        throttle_records = []

        def on_throttle(throttled: bool) -> None:
            throttle_records.append(throttled)

        gov = ResourceGovernor(on_throttle=on_throttle)

        # 1. High Load -> Throttled
        gov.check_and_apply_governance(cpu=CPU_HIGH_THRESHOLD + 5.0, ram=50.0)
        self.assertTrue(gov.is_throttled)
        self.assertEqual(throttle_records[-1], True)

        # 2. Low Load -> Normal Recovery
        gov.check_and_apply_governance(cpu=CPU_LOW_THRESHOLD - 5.0, ram=RAM_LOW_THRESHOLD - 5.0)
        self.assertFalse(gov.is_throttled)
        self.assertEqual(throttle_records[-1], False)

    def test_governor_emergency_restart(self) -> None:
        restart_called = []

        def on_restart() -> None:
            restart_called.append(True)

        gov = ResourceGovernor(on_emergency_restart=on_restart)
        # Fast-forward emergency timer
        gov._emergency_start_time = time.time() - (EMERGENCY_DURATION_SEC + 5.0)
        gov.check_and_apply_governance(cpu=EMERGENCY_CPU_THRESHOLD + 1.0, ram=50.0)

        self.assertTrue(len(restart_called) > 0)

    def test_brain_governor_throttle_hook(self) -> None:
        brain.set_governor_throttle(True)
        self.assertTrue(brain.is_governor_throttled())
        brain.set_governor_throttle(False)
        self.assertFalse(brain.is_governor_throttled())


class TestLogRotator(unittest.TestCase):
    """Tests for Sub-system D: log_rotator.py."""

    def setUp(self) -> None:
        self.test_dir = Path(tempfile.mkdtemp(prefix="zeta_test_rotator_"))
        self.rotator = LogRotator(
            workspace_dir=self.test_dir,
            max_size_bytes=1024,
            retention_days=1,
        )

    def tearDown(self) -> None:
        self.rotator.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_rotate_file_if_oversized(self) -> None:
        test_file = self.test_dir / "diag_logs.csv"
        # Write 2 KB (above 1024 threshold)
        test_file.write_text("X" * 2048, encoding="utf-8")

        rotated = self.rotator.rotate_file_if_oversized(test_file)
        self.assertIsNotNone(rotated)
        self.assertTrue(rotated.exists())
        self.assertFalse(test_file.exists())

    def test_clean_expired_logs(self) -> None:
        expired_file = self.rotator.logs_dir / "diag_logs_20200101_000000.enc"
        expired_file.write_text("encrypted old logs", encoding="utf-8")

        # Set mtime back by 10 days
        past = time.time() - (10 * 86400)
        os.utime(str(expired_file), (past, past))

        deleted = self.rotator.clean_expired_logs()
        self.assertEqual(deleted, 1)
        self.assertFalse(expired_file.exists())


class TestZetaInstaller(unittest.TestCase):
    """Tests for Sub-system E: installer.py."""

    def test_privilege_and_directories(self) -> None:
        admin_flag = is_admin()
        self.assertIsInstance(admin_flag, bool)

        admin_dir = get_default_install_dir(as_admin=True)
        user_dir = get_default_install_dir(as_admin=False)
        self.assertIn("ZetaJarvis", str(admin_dir))
        self.assertIn("ZetaJarvis", str(user_dir))

    def test_installer_dry_run_lifecycle(self) -> None:
        installer = ZetaInstaller(dry_run=True, silent=True)
        # Install in dry-run
        install_res = installer.install()
        self.assertTrue(install_res)

        # Uninstall in dry-run
        uninstall_res = installer.uninstall()
        self.assertTrue(uninstall_res)

    def test_installer_flag_normalization(self) -> None:
        old_argv = sys.argv
        try:
            sys.argv = ["installer.py", "/SILENT", "--dry-run"]
            args = parse_args()
            self.assertTrue(args.silent)
            self.assertTrue(args.dry_run)
        finally:
            sys.argv = old_argv


class TestBuildAssetGeneration(unittest.TestCase):
    """Tests for Sub-system A build packaging assets."""

    def test_version_reading_and_formatting(self) -> None:
        ver_str, quad = read_version()
        self.assertIsInstance(ver_str, str)
        self.assertEqual(len(quad), 4)

    def test_version_info_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_info = Path(tmp) / "file_version_info.txt"
            old_info = globals().get("VERSION_INFO_FILE")
            try:
                import build
                build.VERSION_INFO_FILE = tmp_info
                info_p = generate_version_info_file("1.0.0.0", (1, 0, 0, 0))
                self.assertTrue(info_p.exists())
                content = info_p.read_text(encoding="utf-8")
                self.assertIn("VSVersionInfo", content)
                self.assertIn("ZetaJarvis Enterprise Digital Worker Node", content)
            finally:
                if old_info:
                    build.VERSION_INFO_FILE = old_info

    def test_icon_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_ico = Path(tmp) / "test_icon.ico"
            generated = generate_icon_if_missing(test_ico)
            self.assertTrue(generated.exists())
            self.assertGreater(generated.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
