#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: test_resilience_layer.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Comprehensive test suite for Modules 5, 6, and 7:
#              Startup persistence, Process Guardian, UI automation,
#              Zero-downtime Git self-updater, crash rollback, and main app.
# ------------------------------------------------------------------------------

"""Unit and Integration Test Suite for ZetaJarvis Enterprise Resilience Layer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*Setting the shape on a NumPy array.*")

# Ensure workspace root is in sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import brain
from main import ZetaJarvisDesktopApp
from persistence import (
    AUTO_STARTUP_ENABLED,
    ProcessGuardian,
    StartupManager,
    apply_stealth_mode,
)
from self_update import SelfUpdater
import ui_automation
from ui_automation import (
    ClipboardController,
    InputController,
    WindowController,
    check_abort_phrase,
    is_aborted,
    reset_abort,
    trigger_abort,
)


class TestStartupPersistence(unittest.TestCase):
    """Tests for Module 5: StartupManager and ProcessGuardian."""

    def setUp(self) -> None:
        self.manager = StartupManager(app_name="ZetaJarvisTest", task_name="ZetaTestKeepAlive")

    def test_launch_command_generation(self) -> None:
        cmd = self.manager.get_launch_command()
        self.assertIn("main.py", cmd)
        self.assertTrue(cmd.startswith('"') or cmd.startswith("'"))

    def test_registry_registration_dry_run(self) -> None:
        # Dry-run must return True without modifying registry
        res_reg = self.manager.register_registry(dry_run=True)
        res_unreg = self.manager.unregister_registry(dry_run=True)
        self.assertTrue(res_reg)
        self.assertTrue(res_unreg)

    def test_task_scheduler_dry_run(self) -> None:
        # Dry-run must return True without touching Windows Task Scheduler
        res_reg = self.manager.register_task_scheduler(dry_run=True)
        res_unreg = self.manager.unregister_task_scheduler(dry_run=True)
        self.assertTrue(res_reg)
        self.assertTrue(res_unreg)

    def test_register_all_dry_run(self) -> None:
        success = self.manager.register_all(dry_run=True)
        self.assertTrue(success)

    def test_process_guardian_initialization(self) -> None:
        guardian = ProcessGuardian(target_script="main.py", max_restarts=3, restart_cooldown_sec=0.1)
        self.assertEqual(guardian.max_restarts, 3)
        self.assertEqual(guardian.restart_cooldown, 0.1)
        self.assertFalse(guardian._stop_event.is_set())
        guardian.stop()
        self.assertTrue(guardian._stop_event.is_set())

    def test_stealth_mode_safe_invocation(self) -> None:
        # apply_stealth_mode must never raise exception
        try:
            apply_stealth_mode(minimize_console=False)
        except Exception as exc:
            self.fail(f"apply_stealth_mode raised exception: {exc}")


class TestUIAutomation(unittest.TestCase):
    """Tests for Module 6: UI Automation, Inputs, Clipboard, and Kill-Switch."""

    def setUp(self) -> None:
        reset_abort()

    def tearDown(self) -> None:
        reset_abort()

    def test_clipboard_operations(self) -> None:
        test_payload = f"Zeta_Unit_Test_Token_{int(time.time() * 1000)}"
        write_res = ClipboardController.set_clipboard(test_payload)
        read_back = ClipboardController.get_clipboard()

        if write_res:
            self.assertEqual(read_back, test_payload)
        else:
            # Clipboard may be unavailable in headless/unattended container
            self.assertIsInstance(write_res, bool)

    def test_kill_switch_phrase_detection(self) -> None:
        self.assertTrue(check_abort_phrase("Zeta, abort automation"))
        self.assertTrue(check_abort_phrase("Please abort automation immediately"))
        self.assertTrue(check_abort_phrase("zeta abort"))
        self.assertFalse(check_abort_phrase("What is the weather today?"))
        self.assertFalse(check_abort_phrase("Tell me a story about Zeta"))

    def test_kill_switch_trigger_and_abort_enforcement(self) -> None:
        self.assertFalse(is_aborted())
        trigger_abort()
        self.assertTrue(is_aborted())

        # Operations must immediately return aborted status while kill-switch is active
        res_win = WindowController.control_window("Notepad", "focus")
        self.assertEqual(res_win.get("status"), "aborted")

        res_click = InputController.click_element(100, 100)
        self.assertEqual(res_click.get("status"), "aborted")

        res_type = InputController.type_text("hello")
        self.assertEqual(res_type.get("status"), "aborted")

        reset_abort()
        self.assertFalse(is_aborted())

    def test_window_controller_safe_execution(self) -> None:
        # Looking for a non-existent window must return None, not crash
        hwnd = WindowController.find_window("__Zeta_NonExistent_Window_99999__")
        self.assertIsNone(hwnd)

        # Getting rect for None HWND must return None
        rect = WindowController.get_window_rect(None)
        self.assertIsNone(rect)

    def test_screen_capture_safe_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "test_screen.png"
            res = InputController.capture_screen(output_path=str(out_file))
            # Must return a dictionary with a status key
            self.assertIn("status", res)
            if res["status"] == "success":
                self.assertTrue(out_file.exists())

    def test_brain_tool_registration(self) -> None:
        required_tools = [
            "control_window",
            "click_element",
            "type_text",
            "capture_screen",
            "get_clipboard",
            "set_clipboard",
        ]
        for tool_name in required_tools:
            self.assertIn(
                tool_name,
                brain.TOOL_REGISTRY,
                f"Tool '{tool_name}' must be registered in brain.TOOL_REGISTRY",
            )

        # Check tools_config.json contains their definitions
        config_path = WORKSPACE_ROOT / "tools_config.json"
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            names = {t["function"]["name"] for t in data.get("tools", [])}
            for tool_name in required_tools:
                self.assertIn(tool_name, names, f"Tool '{tool_name}' must be in tools_config.json")


class TestSelfUpdater(unittest.TestCase):
    """Tests for Module 7: Zero-Downtime Self-Updater & Crash Recovery."""

    def setUp(self) -> None:
        self.test_dir = Path(tempfile.mkdtemp(prefix="zeta_test_updater_"))
        self.backup_dir = self.test_dir / "backups"
        self.staging_dir = self.test_dir / "staging"
        self.workspace_dir = self.test_dir / "workspace"

        for d in [self.backup_dir, self.staging_dir, self.workspace_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.updater = SelfUpdater(
            project_dir=self.workspace_dir,
            backup_dir=self.backup_dir,
            staging_dir=self.staging_dir,
        )

        # Create dummy initial workspace files
        (self.workspace_dir / "main.py").write_text("APP_VERSION = '1.0.0'\n", encoding="utf-8")
        (self.workspace_dir / "brain.py").write_text("BRAIN_STATE = 'active'\n", encoding="utf-8")
        (self.workspace_dir / ".env").write_text("SECRET_KEY=confidential\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_git_local_commit_detection(self) -> None:
        real_updater = SelfUpdater()
        commit = real_updater.get_local_commit()
        # In a git repo, commit should be a 40-char SHA string or None
        if commit:
            self.assertIsInstance(commit, str)
            self.assertGreaterEqual(len(commit), 7)

    def test_backup_creation_and_manifest(self) -> None:
        backup_path = self.updater.create_backup(tag="unit_test")
        self.assertTrue(backup_path.exists())
        self.assertTrue(backup_path.is_dir())

        # Manifest must exist with correct metadata
        manifest_path = backup_path / "manifest.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("tag"), "unit_test")
        self.assertIn("timestamp", manifest)

        # Backed up files must exist
        self.assertTrue((backup_path / "main.py").exists())
        self.assertTrue((backup_path / "brain.py").exists())

        # Protected file (.env) must NOT be copied into backup
        self.assertFalse((backup_path / ".env").exists())

    def test_staging_syntax_validation(self) -> None:
        # Valid Python code in staging
        (self.staging_dir / "clean_module.py").write_text("def run():\n    return True\n", encoding="utf-8")
        self.assertTrue(self.updater.validate_staged_code())

        # Invalid syntax in staging
        (self.staging_dir / "broken_module.py").write_text("def bad_syntax(:\n", encoding="utf-8")
        self.assertFalse(self.updater.validate_staged_code())

    def test_atomic_hot_swap(self) -> None:
        # Prepare valid staged update
        (self.staging_dir / "main.py").write_text("APP_VERSION = '2.0.0'\n", encoding="utf-8")

        success = self.updater.apply_hot_swap()
        self.assertTrue(success)

        # Workspace main.py must be updated
        updated_content = (self.workspace_dir / "main.py").read_text(encoding="utf-8")
        self.assertIn("APP_VERSION = '2.0.0'", updated_content)

        # Protected .env must remain untouched
        self.assertTrue((self.workspace_dir / ".env").exists())
        env_content = (self.workspace_dir / ".env").read_text(encoding="utf-8")
        self.assertEqual(env_content, "SECRET_KEY=confidential\n")

    def test_crash_recovery_and_rollback(self) -> None:
        # 1. Create initial snapshot
        backup_path = self.updater.create_backup(tag="pre_crash")

        # 2. Modify workspace with bad code
        (self.workspace_dir / "main.py").write_text("APP_VERSION = 'CRASHED_VERSION'\n", encoding="utf-8")

        # 3. Simulate crash sentinel
        self.updater.flag_file.write_text(
            json.dumps({"status": "in_progress", "backup_path": str(backup_path)}),
            encoding="utf-8",
        )

        # 4. Check startup health: must detect crash and perform rollback
        rollback_occurred = self.updater.check_startup_health_and_rollback_if_needed()
        self.assertTrue(rollback_occurred)

        # 5. File must be restored to version 1.0.0
        restored_content = (self.workspace_dir / "main.py").read_text(encoding="utf-8")
        self.assertIn("APP_VERSION = '1.0.0'", restored_content)

        # 6. Sentinel file must be cleared
        self.assertFalse(self.updater.flag_file.exists())


class TestMainOrchestratorIntegration(unittest.TestCase):
    """Integration tests for main.py with all 7 subsystems."""

    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings("ignore", category=DeprecationWarning)

    def test_main_app_lifecycle_headless(self) -> None:
        app = ZetaJarvisDesktopApp(headless=True, dry_run=True)
        app.start()

        # Check subsystems initialized
        self.assertIsNotNone(app.brain_instance)
        self.assertIsNotNone(app.voice)
        self.assertIsNotNone(app.watchdog)
        self.assertIsNotNone(app.harness)
        self.assertIsNotNone(app.updater)
        self.assertIsNotNone(app.startup_manager)
        # In headless mode, HUD must be None
        self.assertIsNone(app.hud)

        # Test simulated speech handling (UI abort kill-switch)
        ui_automation.reset_abort()
        app._on_speech_recognized("Zeta, abort automation now")
        self.assertTrue(ui_automation.is_aborted())
        ui_automation.reset_abort()

        # Test simulated panic lockdown
        app._on_speech_recognized("Zeta, lockdown")
        self.assertTrue(app._shutdown_event.is_set())

        # Clean shutdown
        app.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
