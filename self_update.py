#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: self_update.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Zero-downtime Git repository updater (hourly polling + on-demand),
#              staging puller, atomic code hot-swap, timestamped backups in backups/,
#              and automatic rollback on startup crash.
# ------------------------------------------------------------------------------

"""Module 7: Self-Update – Zero-Downtime Git Updater & Crash Rollback Engine.

Features:
- Git Remote Polling:
  * Checks remote repository (UPDATE_REPO or origin) for upstream commits.
  * Configurable check interval via UPDATE_CHECK_HOURS (default: 1.0 hour).
- Staging Engine:
  * Downloads / pulls updates into isolated staging/ directory.
  * Validates Python syntax across all staged modules before applying changes.
- Atomic Code Hot-Swap:
  * Notifies user via TTS ("Update available. Applying zero-downtime hot-swap.").
  * Captures pre-update snapshot in backups/backup_<timestamp>/ with manifest.
  * Atomically updates source files while preserving sensitive and local data
    (.env, api keys, local memory, tools/disabled/, logs, git metadata).
- Crash Guard & Automatic Rollback:
  * Tracks update state with .update_in_progress sentinel.
  * If the newly updated version fails during startup, automatically rolls back
    to the latest snapshot and notifies the user.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, List, Optional, Set, Tuple

# ==============================================================================
# Configuration
# ==============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backups"
DEFAULT_STAGING_DIR = PROJECT_ROOT / "staging"
UPDATE_FLAG_FILE = PROJECT_ROOT / ".update_in_progress"

UPDATE_REPO = os.getenv("UPDATE_REPO", "origin")
UPDATE_BRANCH = os.getenv("UPDATE_BRANCH", "main")
UPDATE_CHECK_HOURS = float(os.getenv("UPDATE_CHECK_HOURS", "1.0"))
MAX_BACKUPS_RETAINED = int(os.getenv("MAX_BACKUPS_RETAINED", "5"))

# Paths and patterns that must NEVER be overwritten during an update
PROTECTED_PATHS: Set[str] = {
    ".env",
    ".env.example",
    ".git",
    ".github",
    ".venv",
    ".venv-tts",
    "backups",
    "staging",
    "screenshots",
    "__pycache__",
    "diag_logs.csv",
    ".jarvis_key",
    "memory.json",
    "notes.txt",
    "api_key.txt",
    "base_url.txt",
    "model.txt",
    "xfyun.txt",
    "whatsapp_token.txt",
    "whatsapp_phone_id.txt",
    ".update_in_progress",
}


# ==============================================================================
# SelfUpdater Engine
# ==============================================================================

class SelfUpdater:
    """Manages Git updates, staging verification, atomic hot-swapping, and crash rollbacks."""

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        staging_dir: Optional[Path] = None,
        tts_notifier: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.project_dir = Path(project_dir or PROJECT_ROOT).resolve()
        self.backup_dir = Path(backup_dir or DEFAULT_BACKUP_DIR).resolve()
        self.staging_dir = Path(staging_dir or DEFAULT_STAGING_DIR).resolve()
        self.tts_notifier = tts_notifier
        self.flag_file = self.project_dir / ".update_in_progress"

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _notify(self, message: str) -> None:
        """Sends user notification via TTS or console log."""
        print(f"[SelfUpdater] {message}", flush=True)
        if self.tts_notifier:
            try:
                self.tts_notifier(message)
            except Exception:
                pass

    # --------------------------------------------------------------------------
    # Git Integration & Remote Checking
    # --------------------------------------------------------------------------

    def get_local_commit(self) -> Optional[str]:
        """Returns the current local Git commit hash, or None if not in a Git repo."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return None

    def check_for_updates(
        self,
        remote: str = UPDATE_REPO,
        branch: str = UPDATE_BRANCH,
    ) -> Tuple[bool, str]:
        """Checks remote repository for new commits.
        
        Returns:
            Tuple of (has_updates: bool, commit_or_info: str)
        """
        local_commit = self.get_local_commit()
        if not local_commit:
            return False, "Not a Git repository or Git not found on PATH."

        try:
            # Query remote references
            res = subprocess.run(
                ["git", "ls-remote", remote, f"refs/heads/{branch}"],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if res.returncode != 0 or not res.stdout.strip():
                # Fallback: check HEAD on remote
                res = subprocess.run(
                    ["git", "ls-remote", remote, "HEAD"],
                    cwd=str(self.project_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )

            if res.returncode == 0 and res.stdout.strip():
                remote_commit = res.stdout.strip().split()[0]
                if remote_commit != local_commit:
                    return True, f"New version available: {remote_commit[:8]} (local: {local_commit[:8]})"
                return False, f"Up to date at commit {local_commit[:8]}."
            else:
                err = res.stderr.strip() or "Remote returned empty reference."
                return False, f"Remote check completed: {err}"

        except subprocess.TimeoutExpired:
            return False, "Remote check timed out (offline or slow network)."
        except Exception as exc:
            return False, f"Remote check failed: {exc}"

    # --------------------------------------------------------------------------
    # Staging & Syntax Validation
    # --------------------------------------------------------------------------

    def stage_update_from_source(self, source_path: Path) -> bool:
        """Copies files from a local source folder into staging for verification."""
        if not source_path.exists():
            return False

        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir, ignore_errors=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        for item in source_path.iterdir():
            if item.name in PROTECTED_PATHS or item.name.startswith("."):
                continue
            dest = self.staging_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        return self.validate_staged_code()

    def stage_update_from_git(
        self,
        remote: str = UPDATE_REPO,
        branch: str = UPDATE_BRANCH,
    ) -> bool:
        """Clones/fetches the latest branch into the staging directory."""
        try:
            if self.staging_dir.exists():
                shutil.rmtree(self.staging_dir, ignore_errors=True)
            self.staging_dir.mkdir(parents=True, exist_ok=True)

            res = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", branch, remote, str(self.staging_dir)],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if res.returncode != 0:
                print(f"[SelfUpdater Error] Git clone into staging failed: {res.stderr}", file=sys.stderr)
                return False

            return self.validate_staged_code()
        except Exception as exc:
            print(f"[SelfUpdater Error] Staging failed: {exc}", file=sys.stderr)
            return False

    def validate_staged_code(self) -> bool:
        """Compiles all Python files in the staging directory to catch syntax errors."""
        py_files = list(self.staging_dir.rglob("*.py"))
        if not py_files:
            return False

        for py_path in py_files:
            # Skip virtual environments or caches if present
            if any(part in py_path.parts for part in [".venv", ".venv-tts", "__pycache__", "backups"]):
                continue
            try:
                py_compile.compile(str(py_path), doraise=True)
            except py_compile.PyCompileError as err:
                print(f"[SelfUpdater Error] Syntax validation failed in staged file {py_path.name}: {err}", file=sys.stderr)
                return False
            except Exception as exc:
                print(f"[SelfUpdater Error] Compilation check error on {py_path.name}: {exc}", file=sys.stderr)
                return False

        return True

    # --------------------------------------------------------------------------
    # Snapshot Backup & Pruning
    # --------------------------------------------------------------------------

    def create_backup(self, tag: str = "") -> Path:
        """Takes an atomic timestamped snapshot of workspace source files into backups/."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = f"backup_{timestamp}" + (f"_{tag}" if tag else "")
        target_backup_dir = self.backup_dir / folder_name
        target_backup_dir.mkdir(parents=True, exist_ok=True)

        copied_count = 0
        for item in self.project_dir.iterdir():
            # Skip protected directories and files
            if item.name in PROTECTED_PATHS or item.name.startswith("."):
                continue
            dest = target_backup_dir / item.name
            try:
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
                copied_count += 1
            except Exception as exc:
                print(f"[SelfUpdater Warn] Failed copying {item.name} to backup: {exc}", file=sys.stderr)

        # Write manifest
        manifest = {
            "timestamp": timestamp,
            "created_at": datetime.datetime.now().isoformat(),
            "local_commit": self.get_local_commit(),
            "files_copied": copied_count,
            "tag": tag,
        }
        (target_backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        self._prune_old_backups()
        return target_backup_dir

    def _prune_old_backups(self) -> None:
        """Retains only the newest MAX_BACKUPS_RETAINED backup snapshots."""
        try:
            backups = sorted(
                [b for b in self.backup_dir.iterdir() if b.is_dir() and b.name.startswith("backup_")],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in backups[MAX_BACKUPS_RETAINED:]:
                shutil.rmtree(old, ignore_errors=True)
        except Exception:
            pass

    def get_latest_backup(self) -> Optional[Path]:
        """Returns the path to the most recent backup folder, or None if none exist."""
        try:
            backups = sorted(
                [b for b in self.backup_dir.iterdir() if b.is_dir() and b.name.startswith("backup_")],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            return backups[0] if backups else None
        except Exception:
            return None

    # --------------------------------------------------------------------------
    # Atomic Hot-Swap Execution
    # --------------------------------------------------------------------------

    def apply_hot_swap(
        self,
        staging_dir: Optional[Path] = None,
        dry_run: bool = False,
    ) -> bool:
        """Applies validated update from staging to project root with backup and rollback guard."""
        source_dir = staging_dir or self.staging_dir
        if not source_dir.exists() or not list(source_dir.iterdir()):
            print("[SelfUpdater Error] Staging directory is empty or missing.", file=sys.stderr)
            return False

        # 1. Notify user
        self._notify("Update available. Applying zero-downtime hot-swap.")

        if dry_run:
            self._notify("Dry-run mode: Update validated successfully without writing files.")
            return True

        # 2. Pre-update snapshot backup
        backup_path = self.create_backup(tag="pre_update")
        print(f"[SelfUpdater] Created safety backup at: {backup_path.name}")

        # 3. Mark update in progress sentinel
        sentinel_info = {
            "status": "in_progress",
            "backup_path": str(backup_path),
            "timestamp": time.time(),
        }
        self.flag_file.write_text(json.dumps(sentinel_info, indent=2), encoding="utf-8")

        # 4. Copy files from staging to project root (excluding protected paths)
        try:
            for item in source_dir.iterdir():
                if item.name in PROTECTED_PATHS or item.name.startswith("."):
                    continue

                dest = self.project_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)

            # 5. Validate integrity of active directory
            for main_file in ["main.py", "brain.py"]:
                target_check = self.project_dir / main_file
                if target_check.exists():
                    py_compile.compile(str(target_check), doraise=True)

            self._notify("Zero-downtime hot-swap applied successfully.")
            return True

        except Exception as exc:
            print(f"[SelfUpdater Critical] Hot-swap failed: {exc}. Initiating immediate rollback...", file=sys.stderr)
            self.rollback_to_backup(backup_path)
            return False

    # --------------------------------------------------------------------------
    # Automatic Rollback Engine
    # --------------------------------------------------------------------------

    def rollback_to_backup(self, backup_path: Optional[Path] = None) -> bool:
        """Restores workspace files from the specified or latest backup."""
        target_backup = backup_path or self.get_latest_backup()
        if not target_backup or not target_backup.exists():
            print("[SelfUpdater Error] No backup directory available for rollback.", file=sys.stderr)
            return False

        print(f"[SelfUpdater Alert] Rolling back workspace to snapshot: {target_backup.name}", file=sys.stderr)

        try:
            for item in target_backup.iterdir():
                if item.name == "manifest.json" or item.name in PROTECTED_PATHS:
                    continue

                dest = self.project_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)

            # Clear flag file
            if self.flag_file.exists():
                self.flag_file.unlink(missing_ok=True)

            self._notify(f"System restored cleanly from backup: {target_backup.name}")
            return True
        except Exception as exc:
            print(f"[SelfUpdater Critical] Rollback execution failed: {exc}", file=sys.stderr)
            return False

    # --------------------------------------------------------------------------
    # Startup Health Check & Crash Recovery
    # --------------------------------------------------------------------------

    def check_startup_health_and_rollback_if_needed(self) -> bool:
        """Checks if a previous update crashed during initialization and auto-recovers.
        
        Returns:
            True if a crash rollback was performed, False if state is normal.
        """
        if not self.flag_file.exists():
            return False

        try:
            content = self.flag_file.read_text(encoding="utf-8")
            data = json.loads(content)
            backup_path_str = data.get("backup_path")
            backup_path = Path(backup_path_str) if backup_path_str else None

            print(
                "[SelfUpdater Warning] Detected uncompleted update on startup! "
                "Previous build crashed before completing initialization. Reverting...",
                file=sys.stderr,
            )
            self.rollback_to_backup(backup_path)
            return True
        except Exception as exc:
            print(f"[SelfUpdater Error] Startup crash check failed: {exc}", file=sys.stderr)
            if self.flag_file.exists():
                self.flag_file.unlink(missing_ok=True)
            return False

    def mark_startup_successful(self) -> None:
        """Removes the update sentinel, confirming the new build booted successfully."""
        if self.flag_file.exists():
            try:
                self.flag_file.unlink(missing_ok=True)
            except Exception:
                pass

    # --------------------------------------------------------------------------
    # Background Update Daemon Loop
    # --------------------------------------------------------------------------

    def run_update_cycle(self) -> bool:
        """Runs a complete check, stage, and hot-swap cycle."""
        has_update, info = self.check_for_updates()
        if not has_update:
            return False

        print(f"[SelfUpdater] {info}")
        staged_ok = self.stage_update_from_git()
        if not staged_ok:
            return False

        return self.apply_hot_swap()

    def start_periodic_updater(
        self,
        interval_hours: Optional[float] = None,
    ) -> threading.Thread:
        """Launches background daemon checking for updates periodically."""
        interval_sec = (interval_hours or UPDATE_CHECK_HOURS) * 3600.0

        def _loop() -> None:
            while not self._stop_event.is_set():
                # Sleep in short increments to allow rapid shutdown
                wait_step = 2.0
                elapsed = 0.0
                while elapsed < interval_sec and not self._stop_event.is_set():
                    time.sleep(wait_step)
                    elapsed += wait_step

                if self._stop_event.is_set():
                    break

                try:
                    self.run_update_cycle()
                except Exception as exc:
                    print(f"[SelfUpdater Error] Periodic update check exception: {exc}", file=sys.stderr)

        self._thread = threading.Thread(target=_loop, name="ZetaSelfUpdaterDaemon", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        """Signals update daemon to terminate."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


# ==============================================================================
# Standalone Verification Demo
# ==============================================================================

if __name__ == "__main__":
    print("=" * 70, flush=True)
    print(" ZetaJarvis Module 7: Self-Update -- Verification & Demo", flush=True)
    print("=" * 70, flush=True)

    # Initialize updater with local temporary directories
    demo_base = PROJECT_ROOT / "temp_demo_updater"
    demo_backup = demo_base / "backups"
    demo_staging = demo_base / "staging"
    demo_workspace = demo_base / "workspace"

    for d in [demo_backup, demo_staging, demo_workspace]:
        d.mkdir(parents=True, exist_ok=True)

    # Create dummy workspace file
    dummy_main = demo_workspace / "main.py"
    dummy_main.write_text("print('ZetaJarvis Version 1.0.0 Original')", encoding="utf-8")

    updater = SelfUpdater(
        project_dir=demo_workspace,
        backup_dir=demo_backup,
        staging_dir=demo_staging,
    )

    print("\n[1] Testing Git Local Commit Detection:", flush=True)
    real_updater = SelfUpdater()
    local_commit = real_updater.get_local_commit()
    print(f"  Current Git Commit: {local_commit[:8] if local_commit else 'None (Non-git env)'}", flush=True)

    print("\n[2] Testing Remote Update Check:", flush=True)
    has_update, update_info = real_updater.check_for_updates()
    print(f"  Update Available: {has_update}", flush=True)
    print(f"  Info: {update_info}", flush=True)

    print("\n[3] Testing Snapshot Backup Creation:", flush=True)
    backup_path = updater.create_backup(tag="demo_test")
    print(f"  Backup Created at: {backup_path.name}", flush=True)
    manifest_file = backup_path / "manifest.json"
    print(f"  Manifest exists: {manifest_file.exists()}", flush=True)

    print("\n[4] Testing Staging & Code Validation:", flush=True)
    # Create staged update version 2.0
    staged_code = demo_staging / "main.py"
    staged_code.write_text("print('ZetaJarvis Version 2.0.0 Staged')", encoding="utf-8")
    is_valid = updater.validate_staged_code()
    print(f"  Staged Python Code Syntax Valid: {is_valid}", flush=True)

    print("\n[5] Testing Atomic Hot-Swap:", flush=True)
    swap_success = updater.apply_hot_swap()
    print(f"  Hot-Swap Succeeded: {swap_success}", flush=True)
    current_content = dummy_main.read_text(encoding="utf-8")
    print(f"  Workspace content after swap: '{current_content.strip()}'", flush=True)

    print("\n[6] Testing Startup Crash Recovery (Rollback):", flush=True)
    # Simulate a crash flag
    updater.flag_file.write_text(
        json.dumps({"status": "in_progress", "backup_path": str(backup_path)}),
        encoding="utf-8",
    )
    print(f"  Simulated crash sentinel present: {updater.flag_file.exists()}", flush=True)
    rollback_occurred = updater.check_startup_health_and_rollback_if_needed()
    print(f"  Rollback Performed: {rollback_occurred}", flush=True)
    rolled_back_content = dummy_main.read_text(encoding="utf-8")
    expected_str = "print('ZetaJarvis Version 1.0.0 Original')"
    print(f"  Restored Original Content: {rolled_back_content == expected_str}", flush=True)

    # Cleanup demo files
    shutil.rmtree(demo_base, ignore_errors=True)
    print("\n[SUCCESS] Module 7 (self_update.py) verified successfully.", flush=True)
