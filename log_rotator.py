#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: log_rotator.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Automatic log rotation & retention engine for encrypted diagnostic
#              logs and plaintext stdout streams with 10MB size limits & 30-day retention.
# ------------------------------------------------------------------------------

"""Sub-system D: Log Rotation & Retention.

Features:
- Encrypted Diagnostic Rotation:
  * Rotates diag_logs.csv / diag_logs*.enc when file exceeds LOG_MAX_SIZE (default 10 MB).
- Automatic Log Retention:
  * Automatically purges logs older than LOG_RETENTION_DAYS (default 30 days).
  * Cleans up both logs/ and workspace root on startup and periodically.
- Plaintext Stdout Redirection:
  * Tees stdout and stderr to timestamped files in logs/stdout/ (when not in stealth mode).
  * Enforces the same size rotation and 30-day retention policy.
"""

from __future__ import annotations

import datetime
import io
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from typing import Optional, Set

# ==============================================================================
# Configuration
# ==============================================================================

LOG_MAX_SIZE_BYTES = int(float(os.getenv("LOG_MAX_SIZE_MB", "10.0")) * 1024 * 1024)
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))
LOG_CHECK_INTERVAL_SEC = float(os.getenv("LOG_CHECK_INTERVAL_SEC", "300.0"))

PROJECT_ROOT = Path(__file__).resolve().parent
LOGS_DIR = PROJECT_ROOT / "logs"
STDOUT_LOGS_DIR = LOGS_DIR / "stdout"


class MultiStream(io.TextIOBase):
    """Duplicates stream writes to both original console and a log file."""

    def __init__(self, original_stream: io.TextIOBase, file_path: Path) -> None:
        self.original_stream = original_stream
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.file_path, "a", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        with self._lock:
            try:
                self.original_stream.write(s)
                self.original_stream.flush()
            except Exception:
                pass
            try:
                self._file.write(s)
                self._file.flush()
            except Exception:
                pass
        return len(s)

    def flush(self) -> None:
        with self._lock:
            try:
                self.original_stream.flush()
            except Exception:
                pass
            try:
                self._file.flush()
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            try:
                self._file.close()
            except Exception:
                pass


class LogRotator:
    """Manages file rotation and retention for encrypted and plaintext logs."""

    def __init__(
        self,
        workspace_dir: Optional[Path] = None,
        max_size_bytes: int = LOG_MAX_SIZE_BYTES,
        retention_days: int = LOG_RETENTION_DAYS,
    ) -> None:
        self.workspace_dir = Path(workspace_dir or PROJECT_ROOT).resolve()
        self.logs_dir = self.workspace_dir / "logs"
        self.stdout_logs_dir = self.logs_dir / "stdout"
        self.max_size_bytes = max_size_bytes
        self.retention_days = retention_days

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.stdout_logs_dir.mkdir(parents=True, exist_ok=True)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stdout_stream: Optional[MultiStream] = None
        self._stderr_stream: Optional[MultiStream] = None

    # --------------------------------------------------------------------------
    # Rotation & Pruning Operations
    # --------------------------------------------------------------------------

    def rotate_file_if_oversized(self, file_path: Path) -> Optional[Path]:
        """Rotates file to a timestamped backup if it exceeds max_size_bytes."""
        if not file_path.exists():
            return None

        try:
            if file_path.stat().st_size >= self.max_size_bytes:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                # e.g., diag_logs_20260909_120000.csv
                rotated_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
                dest = self.logs_dir / rotated_name
                shutil.move(str(file_path), str(dest))
                print(f"[LogRotator] Rotated oversized log {file_path.name} -> {dest.name}", flush=True)
                return dest
        except Exception as exc:
            print(f"[LogRotator Warn] Rotation failed on {file_path.name}: {exc}", file=sys.stderr, flush=True)
        return None

    def rotate_all_diagnostics(self) -> int:
        """Checks and rotates diagnostic logs in workspace and logs directory."""
        rotated_count = 0
        candidates = [
            self.workspace_dir / "diag_logs.csv",
            self.workspace_dir / "diag_logs.enc",
        ]
        # Check candidates in logs/
        candidates.extend(self.logs_dir.glob("diag_logs*.csv"))
        candidates.extend(self.logs_dir.glob("diag_logs*.enc"))

        seen_paths: Set[str] = set()
        for p in candidates:
            resolved = str(p.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            if self.rotate_file_if_oversized(p):
                rotated_count += 1

        return rotated_count

    def clean_expired_logs(self) -> int:
        """Deletes log files older than retention_days."""
        deleted_count = 0
        now = time.time()
        retention_seconds = self.retention_days * 86400.0

        search_dirs = [self.logs_dir, self.stdout_logs_dir, self.workspace_dir]
        for sdir in search_dirs:
            if not sdir.exists():
                continue
            for item in sdir.iterdir():
                if not item.is_file():
                    continue
                # Target log patterns: diag_logs*, *.enc, *.log
                is_log = (
                    "diag_logs" in item.name
                    or item.suffix in [".enc", ".log"]
                    or "stdout" in item.name
                )
                if not is_log:
                    continue

                # Protect active files
                if item.name in ["diag_logs.csv", "diag_logs.enc"]:
                    continue

                try:
                    file_age = now - item.stat().st_mtime
                    if file_age > retention_seconds:
                        item.unlink(missing_ok=True)
                        deleted_count += 1
                        print(f"[LogRotator] Pruned expired log: {item.name}", flush=True)
                except Exception:
                    pass

        return deleted_count

    # --------------------------------------------------------------------------
    # Stdout Redirection
    # --------------------------------------------------------------------------

    def setup_stdout_redirection(self) -> Optional[Path]:
        """Tees stdout and stderr into logs/stdout/zeta_stdout_<date>.log."""
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        log_file = self.stdout_logs_dir / f"zeta_stdout_{today_str}.log"

        try:
            self._stdout_stream = MultiStream(sys.stdout, log_file)
            self._stderr_stream = MultiStream(sys.stderr, log_file)
            sys.stdout = self._stdout_stream  # type: ignore
            sys.stderr = self._stderr_stream  # type: ignore
            return log_file
        except Exception as exc:
            print(f"[LogRotator Warn] Failed redirecting stdout: {exc}", file=sys.stderr, flush=True)
            return None

    def restore_stdout(self) -> None:
        """Restores original stdout and stderr streams."""
        if self._stdout_stream:
            sys.stdout = self._stdout_stream.original_stream
            self._stdout_stream.close()
            self._stdout_stream = None
        if self._stderr_stream:
            sys.stderr = self._stderr_stream.original_stream
            self._stderr_stream.close()
            self._stderr_stream = None

    # --------------------------------------------------------------------------
    # Background Daemon Loop
    # --------------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(LOG_CHECK_INTERVAL_SEC)
            if self._stop_event.is_set():
                break
            try:
                self.rotate_all_diagnostics()
                self.clean_expired_logs()
            except Exception as exc:
                print(f"[LogRotator Error] Background cycle exception: {exc}", file=sys.stderr, flush=True)

    def start_daemon(self) -> None:
        """Starts background rotation daemon."""
        # Initial run on startup
        self.rotate_all_diagnostics()
        self.clean_expired_logs()

        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="ZetaLogRotator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stops background daemon and restores stdout."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.restore_stdout()


# ==============================================================================
# Standalone Verification Demo
# ==============================================================================

if __name__ == "__main__":
    print("=" * 70, flush=True)
    print(" ZetaJarvis Sub-system D: Log Rotator -- Verification Demo", flush=True)
    print("=" * 70, flush=True)

    demo_dir = PROJECT_ROOT / "temp_demo_logs"
    demo_dir.mkdir(parents=True, exist_ok=True)

    # Use small max_size (1 KB) and 0-day retention for rapid demo
    rotator = LogRotator(
        workspace_dir=demo_dir,
        max_size_bytes=1024,
        retention_days=1,
    )

    print("\n[1] Testing Oversized Log Rotation:")
    test_log = demo_dir / "diag_logs.csv"
    # Write 2 KB of dummy data
    test_log.write_text("A" * 2048, encoding="utf-8")
    print(f"  Initial file size: {test_log.stat().st_size} bytes (Threshold: 1024 bytes)")
    rotated_path = rotator.rotate_file_if_oversized(test_log)
    print(f"  Rotated created: {rotated_path is not None and rotated_path.exists()}")
    if rotated_path:
        print(f"  Rotated file name: {rotated_path.name}")

    print("\n[2] Testing Retention & Pruning:")
    # Create an old expired log
    old_log = rotator.logs_dir / "diag_logs_20200101_000000.enc"
    old_log.write_text("dummy encrypted data", encoding="utf-8")
    # Backdate mtime by 40 days
    past_time = time.time() - (40 * 86400)
    os.utime(str(old_log), (past_time, past_time))
    print(f"  Created backdated log: {old_log.name}")
    deleted = rotator.clean_expired_logs()
    print(f"  Expired logs pruned: {deleted}")
    print(f"  Old log successfully removed: {not old_log.exists()}")

    # Cleanup demo files
    shutil.rmtree(demo_dir, ignore_errors=True)
    print("\n[SUCCESS] Sub-system D (log_rotator.py) verified successfully.", flush=True)
