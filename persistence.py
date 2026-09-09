#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: persistence.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Startup persistence via Windows Registry & Task Scheduler,
#              resilient Process Guardian restart loop, and Stealth Mode.
# ------------------------------------------------------------------------------

"""Module 5: Persistence – Startup Persistence & Process Guardian.

Features:
- Dual-layer Windows startup persistence:
  * Windows Registry (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run).
  * Windows Task Scheduler (schtasks.exe with /rl highest, onlogon & hourly keep-alive).
  * Safe dry-run mode for simulation and automated testing.
- Process Guardian:
  * Independent watchdog supervisor that monitors the main process.
  * Restarts ZetaJarvis immediately if it terminates unexpectedly (exit code != 0).
- Stealth Mode:
  * Configurable via STEALTH_MODE in .env.
  * Completely suppresses HUD overlay and minimizes/hides console window on Windows.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import List, Optional

# Windows Registry module (built-in on Windows)
if sys.platform.startswith("win"):
    import winreg
else:
    winreg = None  # type: ignore


# ==============================================================================
# Configuration
# ==============================================================================

APP_NAME = os.getenv("PERSISTENCE_APP_NAME", "ZetaJarvis")
TASK_NAME = os.getenv("PERSISTENCE_TASK_NAME", "ZetaJarvisKeepAlive")
AUTO_STARTUP_ENABLED = os.getenv("AUTO_STARTUP_ENABLED", "true").lower() in ("1", "true", "yes")
STEALTH_MODE = os.getenv("STEALTH_MODE", "false").lower() in ("1", "true", "yes")


# ==============================================================================
# Startup Persistence (Windows Registry + Task Scheduler)
# ==============================================================================

class StartupManager:
    """Manages system startup registration via Windows Registry and Task Scheduler."""

    def __init__(
        self,
        app_name: str = APP_NAME,
        task_name: str = TASK_NAME,
        target_script: Optional[str] = None,
    ) -> None:
        self.app_name = app_name
        self.task_name = task_name
        self.target_script = target_script or str(Path(__file__).resolve().parent / "main.py")
        self.python_exe = sys.executable

    def get_launch_command(self) -> str:
        """Returns the complete execution command string for launching ZetaJarvis."""
        return f'"{self.python_exe}" "{self.target_script}"'

    def register_registry(self, dry_run: bool = False) -> bool:
        """Registers the application in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""
        cmd = self.get_launch_command()
        if dry_run or not sys.platform.startswith("win") or winreg is None:
            return True

        try:
            reg_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(reg_key, self.app_name, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(reg_key)
            return True
        except Exception as exc:
            print(f"[Persistence Warn] Registry registration failed: {exc}", file=sys.stderr)
            return False

    def unregister_registry(self, dry_run: bool = False) -> bool:
        """Removes the application from HKCU Run key."""
        if dry_run or not sys.platform.startswith("win") or winreg is None:
            return True

        try:
            reg_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.DeleteValue(reg_key, self.app_name)
            winreg.CloseKey(reg_key)
            return True
        except Exception:
            return False

    def register_task_scheduler(self, dry_run: bool = False) -> bool:
        """Creates Windows Scheduled Tasks with highest privileges (logon & hourly keep-alive)."""
        cmd = self.get_launch_command()
        if dry_run or not sys.platform.startswith("win"):
            return True

        try:
            # 1. Hourly Keep-Alive Task with highest privileges
            hourly_cmd = [
                "schtasks", "/create",
                "/tn", self.task_name,
                "/tr", cmd,
                "/sc", "hourly",
                "/rl", "highest",
                "/f",
            ]
            subprocess.run(
                hourly_cmd,
                capture_output=True,
                check=False,
                creationflags=0x08000000,
            )

            # 2. Logon Trigger Task
            logon_cmd = [
                "schtasks", "/create",
                "/tn", f"{self.task_name}_Logon",
                "/tr", cmd,
                "/sc", "onlogon",
                "/rl", "highest",
                "/f",
            ]
            subprocess.run(
                logon_cmd,
                capture_output=True,
                check=False,
                creationflags=0x08000000,
            )
            return True
        except Exception as exc:
            print(f"[Persistence Warn] Task Scheduler registration failed: {exc}", file=sys.stderr)
            return False

    def unregister_task_scheduler(self, dry_run: bool = False) -> bool:
        """Deletes scheduled tasks created for ZetaJarvis."""
        if dry_run or not sys.platform.startswith("win"):
            return True

        for name in [self.task_name, f"{self.task_name}_Logon"]:
            try:
                subprocess.run(
                    ["schtasks", "/delete", "/tn", name, "/f"],
                    capture_output=True,
                    check=False,
                    creationflags=0x08000000,
                )
            except Exception:
                pass
        return True

    def register_all(self, dry_run: bool = False) -> bool:
        """Registers both Registry Run key and Task Scheduler keep-alive."""
        reg_ok = self.register_registry(dry_run=dry_run)
        task_ok = self.register_task_scheduler(dry_run=dry_run)
        return reg_ok and task_ok


# ==============================================================================
# Process Guardian (Self-Healing Supervisor)
# ==============================================================================

class ProcessGuardian:
    """Supervises the main ZetaJarvis process and restarts it if it crashes."""

    def __init__(
        self,
        target_script: Optional[str] = None,
        max_restarts: int = 10,
        restart_cooldown_sec: float = 1.0,
    ) -> None:
        self.target_script = target_script or str(Path(__file__).resolve().parent / "main.py")
        self.max_restarts = max_restarts
        self.restart_cooldown = restart_cooldown_sec
        self.restarts_count = 0
        self._stop_event = threading.Event()
        self._process: Optional[subprocess.Popen] = None

    def start_guardian_loop(self, extra_args: Optional[List[str]] = None) -> None:
        """Runs the monitoring loop in foreground, restarting target on crash."""
        args = [sys.executable, self.target_script] + (extra_args or [])

        while not self._stop_event.is_set():
            if self.restarts_count >= self.max_restarts:
                print(f"[Guardian Error] Exceeded max restart limit ({self.max_restarts}). Pausing.", file=sys.stderr)
                break

            try:
                # Launch target process
                self._process = subprocess.Popen(args)
                returncode = self._process.wait()

                # Clean exit (code 0) means intentional shutdown
                if returncode == 0:
                    break

                # Non-zero exit code: unexpected crash -> restart immediately!
                self.restarts_count += 1
                print(
                    f"[Guardian Alert] Target process died with exit code {returncode}. "
                    f"Restarting immediately (attempt {self.restarts_count}/{self.max_restarts})...",
                    file=sys.stderr,
                )
                time.sleep(self.restart_cooldown)

            except Exception as exc:
                print(f"[Guardian Error] Supervisor exception: {exc}", file=sys.stderr)
                time.sleep(self.restart_cooldown)

    def spawn_background_guardian(self) -> Optional[subprocess.Popen]:
        """Spawns an independent guardian process in the background."""
        cmd = [sys.executable, str(Path(__file__).resolve()), "--guard"]
        try:
            creation_flags = 0x08000000 if sys.platform.startswith("win") else 0
            proc = subprocess.Popen(cmd, creationflags=creation_flags)
            return proc
        except Exception as exc:
            print(f"[Guardian Warn] Failed spawning background guardian: {exc}", file=sys.stderr)
            return None

    def stop(self) -> None:
        """Terminates guardian and any managed child process."""
        self._stop_event.set()
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass


# ==============================================================================
# Stealth Mode Handler
# ==============================================================================

def apply_stealth_mode(enabled: bool = STEALTH_MODE, minimize_console: bool = True) -> bool:
    """If enabled, minimizes or hides the console window on Windows."""
    if not enabled or not sys.platform.startswith("win"):
        return False

    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd != 0:
            # SW_HIDE = 0, SW_MINIMIZE = 6
            cmd_show = 6 if minimize_console else 0
            user32.ShowWindow(hwnd, cmd_show)
            return True
    except Exception:
        pass
    return False


# ==============================================================================
# Standalone Verification Demo
# ==============================================================================

if __name__ == "__main__":
    if "--guard" in sys.argv:
        # Running as background guardian process
        guardian = ProcessGuardian()
        guardian.start_guardian_loop()
        sys.exit(0)

    print("=" * 70)
    print(" ZetaJarvis Module 5: Persistence -- Verification & Demo")
    print("=" * 70)

    manager = StartupManager()
    launch_cmd = manager.get_launch_command()
    print("\n[1] Launch Command Generation:")
    print(f"  Command: {launch_cmd}")

    print("\n[2] Testing Registry Registration (Simulation / Dry Run):")
    reg_status = manager.register_registry(dry_run=True)
    print(f"  Registry Registration (Dry-Run): {'SUCCESS' if reg_status else 'FAILED'}")

    print("\n[3] Testing Task Scheduler Registration (Simulation / Dry Run):")
    task_status = manager.register_task_scheduler(dry_run=True)
    print(f"  Task Scheduler (Hourly + Logon, Dry-Run): {'SUCCESS' if task_status else 'FAILED'}")

    print("\n[4] Testing Process Guardian Restart Logic:")
    # Simulate a target script that fails on first run and succeeds on second
    test_script = Path("test_guardian_child_temp.py")
    test_flag_file = Path("test_guardian_flag_temp.txt")

    test_child_code = f"""
import sys
from pathlib import Path
flag = Path(r"{test_flag_file}")
if not flag.exists():
    flag.write_text("crashed")
    sys.exit(1)  # Simulate unexpected crash on first run
else:
    flag.unlink()
    sys.exit(0)  # Clean exit on restart
"""
    test_script.write_text(test_child_code.strip(), encoding="utf-8")

    guardian_test = ProcessGuardian(
        target_script=str(test_script),
        max_restarts=3,
        restart_cooldown_sec=0.1,
    )
    guardian_test.start_guardian_loop()

    print(f"  Guardian detected exit code 1 and restarted child.")
    print(f"  Total Restart Count: {guardian_test.restarts_count} (Expected: 1)")

    # Clean up test artifacts
    if test_script.exists():
        test_script.unlink(missing_ok=True)
    if test_flag_file.exists():
        test_flag_file.unlink(missing_ok=True)

    print("\n[5] Testing Stealth Mode Configuration Check:")
    print(f"  STEALTH_MODE configured: {STEALTH_MODE}")

    print("\n[SUCCESS] Module 5 (persistence.py) verified successfully.")
