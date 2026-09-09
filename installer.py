#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: installer.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Professional one-click installer & uninstaller for Windows.
#              Copies binary, installs shortcuts, registers startup persistence,
#              handles UAC elevation, and supports /SILENT unattended deployment.
# ------------------------------------------------------------------------------

"""Sub-system E: One-Click Installer & Uninstaller.

Features:
- Privilege Detection & Dual Target:
  * Admin: Installs to %ProgramFiles%\\ZetaJarvis.
  * Non-Admin: Installs to %LocalAppData%\\Programs\\ZetaJarvis.
- File Deployment:
  * Deploys ZetaJarvis.exe, tools_config.json, .env.example, icon.ico, VERSION.txt.
- Shortcut Management:
  * Creates desktop and Start Menu shortcuts with embedded icon.
- Dual Persistence Setup:
  * Integrates with persistence.py to configure HKCU Run and Task Scheduler keep-alive.
- Idempotency & Clean Uninstallation:
  * Re-running seamlessly updates existing deployment without duplicate entries.
  * --uninstall cleanly strips shortcuts, scheduled tasks, registry entries, and files.
- Enterprise Automation:
  * Supports /SILENT and --silent for unattended scripted rollouts.
  * Supports --dry-run for non-destructive test validation.
"""

from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Optional, Tuple

from persistence import StartupManager

PROJECT_ROOT = Path(__file__).resolve().parent


def is_admin() -> bool:
    """Returns True if the current process has Windows Administrator privileges."""
    if not sys.platform.startswith("win"):
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def request_admin_elevation() -> bool:
    """Attempts to relaunch the installer with elevated UAC privileges."""
    if not sys.platform.startswith("win"):
        return False
    try:
        params = " ".join([f'"{a}"' for a in sys.argv[1:]])
        # ShellExecuteEx with 'runas' verb triggers UAC elevation prompt
        ret = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            f'"{sys.argv[0]}" {params}',
            None,
            1,  # SW_SHOWNORMAL
        )
        return ret > 32
    except Exception:
        return False


def get_default_install_dir(as_admin: bool) -> Path:
    """Determines the standard installation directory based on privilege level."""
    if as_admin:
        program_files = os.getenv("ProgramFiles", r"C:\Program Files")
        return Path(program_files) / "ZetaJarvis"
    else:
        local_app_data = os.getenv("LocalAppData", str(Path.home() / "AppData" / "Local"))
        return Path(local_app_data) / "Programs" / "ZetaJarvis"


def get_desktop_dir() -> Path:
    """Returns the current user's Desktop directory."""
    user_profile = Path.home()
    desktop = user_profile / "Desktop"
    if desktop.exists():
        return desktop
    onedrive_desktop = user_profile / "OneDrive" / "Desktop"
    if onedrive_desktop.exists():
        return onedrive_desktop
    return desktop


def get_start_menu_dir() -> Path:
    """Returns the user's Start Menu Programs directory."""
    appdata = os.getenv("AppData", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "ZetaJarvis"


def create_windows_shortcut(
    target_path: Path,
    shortcut_path: Path,
    icon_path: Optional[Path] = None,
    working_dir: Optional[Path] = None,
    description: str = "ZetaJarvis Enterprise Automation Node",
    dry_run: bool = False,
) -> bool:
    """Creates a Windows .lnk shortcut file via PowerShell WScript.Shell."""
    if dry_run or not sys.platform.startswith("win"):
        return True

    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    icon_arg = f'$s.IconLocation = "{icon_path}";' if icon_path and icon_path.exists() else ""
    workdir_arg = f'$s.WorkingDirectory = "{working_dir}";' if working_dir else ""

    ps_script = (
        f'$w = New-Object -ComObject WScript.Shell;'
        f'$s = $w.CreateShortcut("{shortcut_path}");'
        f'$s.TargetPath = "{target_path}";'
        f'{workdir_arg}'
        f'{icon_arg}'
        f'$s.Description = "{description}";'
        f'$s.Save();'
    )

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=0x08000000,
        )
        return res.returncode == 0
    except Exception:
        return False


class ZetaInstaller:
    """Manages the installation, shortcut creation, persistence, and uninstallation."""

    def __init__(
        self,
        install_dir: Optional[Path] = None,
        source_dir: Optional[Path] = None,
        silent: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.admin = is_admin()
        self.install_dir = Path(install_dir or get_default_install_dir(self.admin)).resolve()
        self.source_dir = Path(source_dir or PROJECT_ROOT).resolve()
        self.silent = silent
        self.dry_run = dry_run

    def log(self, message: str) -> None:
        if not self.silent:
            print(f"[ZetaInstaller] {message}", flush=True)

    def install(self) -> bool:
        """Executes full idempotent installation routine."""
        self.log(f"Starting installation to: {self.install_dir}")
        self.log(f"Privilege level: {'Administrator' if self.admin else 'Standard User'}")

        if not self.dry_run:
            self.install_dir.mkdir(parents=True, exist_ok=True)

        # 1. Copy Files
        files_to_deploy = [
            "tools_config.json",
            ".env.example",
            "icon.ico",
            "VERSION.txt",
        ]

        # Determine binary location: dist/ZetaJarvis.exe or main.py
        dist_exe = self.source_dir / "dist" / "ZetaJarvis.exe"
        installed_exe = self.install_dir / "ZetaJarvis.exe"

        if dist_exe.exists():
            self.log(f"Copying executable: {dist_exe.name}")
            if not self.dry_run:
                shutil.copy2(dist_exe, installed_exe)
        else:
            self.log("Compiled ZetaJarvis.exe not in dist/. Deploying main script entry...")
            if not self.dry_run:
                shutil.copy2(self.source_dir / "main.py", self.install_dir / "main.py")
                installed_exe = self.install_dir / "main.py"

        # Copy data and config files
        for fname in files_to_deploy:
            src_file = self.source_dir / fname
            if src_file.exists() and not self.dry_run:
                shutil.copy2(src_file, self.install_dir / fname)

        self.log("Deployed application and configuration assets.")

        # 2. Create Desktop Shortcut
        desktop_dir = get_desktop_dir()
        desktop_shortcut = desktop_dir / "ZetaJarvis.lnk"
        icon_path = self.install_dir / "icon.ico"

        shortcut_target = installed_exe
        self.log(f"Creating Desktop shortcut: {desktop_shortcut.name}")
        create_windows_shortcut(
            target_path=shortcut_target,
            shortcut_path=desktop_shortcut,
            icon_path=icon_path if icon_path.exists() else None,
            working_dir=self.install_dir,
            dry_run=self.dry_run,
        )

        # 3. Create Start Menu Shortcut
        start_menu_dir = get_start_menu_dir()
        start_shortcut = start_menu_dir / "ZetaJarvis.lnk"
        self.log(f"Creating Start Menu shortcut: {start_shortcut}")
        create_windows_shortcut(
            target_path=shortcut_target,
            shortcut_path=start_shortcut,
            icon_path=icon_path if icon_path.exists() else None,
            working_dir=self.install_dir,
            dry_run=self.dry_run,
        )

        # 4. Configure Dual Startup Persistence
        self.log("Configuring Windows startup persistence (Registry + Task Scheduler)...")
        startup_mgr = StartupManager(
            target_script=str(installed_exe),
        )
        persist_ok = startup_mgr.register_all(dry_run=self.dry_run)
        if persist_ok:
            self.log("Persistence registered successfully.")
        else:
            self.log("Persistence registration completed with notices.")

        self.log("Installation completed successfully!")
        return True

    def uninstall(self) -> bool:
        """Executes complete cleanup and uninstallation."""
        self.log(f"Initiating uninstallation from: {self.install_dir}")

        # 1. Unregister persistence
        self.log("Removing startup persistence entries...")
        startup_mgr = StartupManager()
        startup_mgr.unregister_registry(dry_run=self.dry_run)
        startup_mgr.unregister_task_scheduler(dry_run=self.dry_run)

        # 2. Remove shortcuts
        desktop_shortcut = get_desktop_dir() / "ZetaJarvis.lnk"
        if desktop_shortcut.exists() and not self.dry_run:
            desktop_shortcut.unlink(missing_ok=True)
            self.log("Removed Desktop shortcut.")

        start_menu_dir = get_start_menu_dir()
        if start_menu_dir.exists() and not self.dry_run:
            shutil.rmtree(start_menu_dir, ignore_errors=True)
            self.log("Removed Start Menu entries.")

        # 3. Remove installation folder
        if self.install_dir.exists() and not self.dry_run:
            shutil.rmtree(self.install_dir, ignore_errors=True)
            self.log("Removed application files directory.")

        self.log("ZetaJarvis has been uninstalled successfully.")
        return True


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def parse_args() -> argparse.Namespace:
    # Normalize Windows-style flags (e.g. /SILENT, /uninstall)
    normalized_argv = []
    for arg in sys.argv[1:]:
        if arg.upper() in ("/SILENT", "/S"):
            normalized_argv.append("--silent")
        elif arg.upper() in ("/UNINSTALL", "/U"):
            normalized_argv.append("--uninstall")
        else:
            normalized_argv.append(arg)

    parser = argparse.ArgumentParser(description="ZetaJarvis Enterprise Installer")
    parser.add_argument("--silent", "-s", action="store_true", help="Unattended silent installation")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall ZetaJarvis and remove all entries")
    parser.add_argument("--install-dir", type=str, help="Custom installation directory")
    parser.add_argument("--dry-run", action="store_true", help="Simulate installation without touching disk")
    return parser.parse_args(normalized_argv)


if __name__ == "__main__":
    args = parse_args()

    # Check elevation if not silent and not running uninstall or dry-run
    if not is_admin() and not args.silent and not args.dry_run and not args.uninstall:
        print("[ZetaInstaller] Requesting administrator elevation for system-wide install...", flush=True)
        # Attempt elevation; if declined, continue as standard user
        elevated = request_admin_elevation()
        if elevated:
            sys.exit(0)
        print("[ZetaInstaller] Continuing installation with standard user permissions.", flush=True)

    installer = ZetaInstaller(
        install_dir=Path(args.install_dir) if args.install_dir else None,
        silent=args.silent,
        dry_run=args.dry_run,
    )

    if args.uninstall:
        success = installer.uninstall()
    else:
        success = installer.install()

    sys.exit(0 if success else 1)
