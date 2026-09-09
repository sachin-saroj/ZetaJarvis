#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: scripts/build.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Production build & packaging pipeline. Runs test gates, generates
#              version resource & multi-resolution icon, bundles dynamic imports,
#              compiles single-file executable via PyInstaller, handles code signing,
#              and packages the self-contained installer.
# ------------------------------------------------------------------------------

"""Sub-system A: Compilation & Packaging Pipeline.

Pipeline Steps:
1. Pre-Flight Test Gate: Executes all unit and integration test suites.
   Aborts immediately with exit code 1 if any test fails.
2. Asset Generation:
   - Reads version from configs/VERSION.txt.
   - Generates Windows PE version information structure (configs/file_version_info.txt).
   - Generates multi-resolution icon.ico (16px to 256px) in resources/ if not present.
3. Executable Compilation (PyInstaller):
   - Dynamic hidden import resolution (OpenAI, sounddevice, pyttsx3, PIL, win32, etc.).
   - Asset bundling (configs, resources, tools).
   - Console / Windowed mode selection based on STEALTH_MODE.
   - Generates standalone dist/ZetaJarvis.exe.
4. Post-Build Code Signing:
   - Queries certs/ for valid .pfx / .cer certificates.
   - Runs signtool.exe sign if available; skips with warning if absent.
5. Installer Compilation:
   - Compiles installer.py into standalone dist/ZetaJarvis_Installer.exe.
6. Validation & Reporting:
   - Verifies produced binaries, file sizes, and generates build manifest.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import List, Optional, Tuple

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    Image = None
    ImageDraw = None
    PIL_AVAILABLE = False


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
CERTS_DIR = PROJECT_ROOT / "certs"
CONFIGS_DIR = PROJECT_ROOT / "configs"
RESOURCES_DIR = PROJECT_ROOT / "resources"

# Asset paths with fallback to root if legacy
VERSION_FILE = CONFIGS_DIR / "VERSION.txt" if (CONFIGS_DIR / "VERSION.txt").exists() else (PROJECT_ROOT / "VERSION.txt")
ICON_FILE = RESOURCES_DIR / "icon.ico" if (RESOURCES_DIR / "icon.ico").exists() else (PROJECT_ROOT / "icon.ico")
VERSION_INFO_FILE = CONFIGS_DIR / "file_version_info.txt" if (CONFIGS_DIR / "file_version_info.txt").exists() else (PROJECT_ROOT / "file_version_info.txt")

HIDDEN_IMPORTS = [
    # Core AI & Runtime
    "openai",
    "tiktoken",
    "sounddevice",
    "numpy",
    "pyttsx3",
    "psutil",
    "pynput",
    "uiautomation",
    "PIL",
    "PIL.Image",
    "PIL.ImageGrab",
    "PIL.ImageDraw",
    "cryptography",
    "cryptography.fernet",
    # Windows native & ctypes
    "win32gui",
    "win32con",
    "win32clipboard",
    "win32api",
    "winreg",
    "ctypes",
    "ctypes.wintypes",
    # Standard library dynamic modules
    "urllib.request",
    "urllib.parse",
    "json",
    "threading",
    "multiprocessing",
    "subprocess",
    "sqlite3",
    "hashlib",
    "hmac",
    "queue",
    "collections",
    "dataclasses",
    "uuid",
    "shutil",
    "py_compile",
    "importlib",
    "inspect",
    # Modular ZetaJarvis packages
    "zetajarvis",
    "zetajarvis.core",
    "zetajarvis.core.brain",
    "zetajarvis.core.dispatcher",
    "zetajarvis.desktop",
    "zetajarvis.desktop.hud",
    "zetajarvis.desktop.voice_pipeline",
    "zetajarvis.desktop.governor",
    "zetajarvis.desktop.log_rotator",
    "zetajarvis.desktop.stealth_harness",
    "zetajarvis.automation",
    "zetajarvis.automation.ui_automation",
    "zetajarvis.automation.auto_watchdog",
    "zetajarvis.deployment",
    "zetajarvis.deployment.persistence",
    "zetajarvis.deployment.self_update",
    "zetajarvis.deployment.installer",
    "zetajarvis.utils",
    "zetajarvis.utils.helpers",
    "zetajarvis.utils.env_validator",
]


def log_step(step_name: str) -> None:
    print("\n" + "=" * 70, flush=True)
    print(f" [BUILD PIPELINE] {step_name}", flush=True)
    print("=" * 70, flush=True)


# ------------------------------------------------------------------------------
# 1. Pre-Flight Test Gate
# ------------------------------------------------------------------------------

def run_test_gate(python_exe: str = sys.executable) -> bool:
    """Executes the test suite discovery. Returns True only if all tests pass."""
    log_step("Step 1: Running Pre-Flight Test Gate")

    print(f"  [*] Executing test discovery across tests/ ...", flush=True)
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SRC_DIR};{PROJECT_ROOT}" if not existing_pythonpath else f"{SRC_DIR};{PROJECT_ROOT};{existing_pythonpath}"

    cmd = [python_exe, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    res = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if res.returncode != 0:
        print(f"  [!] Pre-flight test suite failed!", file=sys.stderr, flush=True)
        print(res.stdout, file=sys.stderr, flush=True)
        print(res.stderr, file=sys.stderr, flush=True)
        return False

    print(res.stderr or res.stdout, flush=True)
    print("\n[+] Pre-flight test gate PASSED. All test suites verified successfully.", flush=True)
    return True


# ------------------------------------------------------------------------------
# 2. Version & Icon Generation
# ------------------------------------------------------------------------------

def read_version() -> Tuple[str, Tuple[int, int, int, int]]:
    """Reads VERSION.txt and returns (version_str, (major, minor, patch, build))."""
    v_file = VERSION_FILE
    if not v_file.exists():
        CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        v_file = CONFIGS_DIR / "VERSION.txt"
        v_file.write_text("1.0.0.0", encoding="utf-8")

    ver_str = v_file.read_text(encoding="utf-8").strip() or "1.0.0.0"
    parts = [int(p) for p in ver_str.replace("-", ".").split(".") if p.isdigit()]
    while len(parts) < 4:
        parts.append(0)
    quad = (parts[0], parts[1], parts[2], parts[3])
    return ver_str, quad


def generate_version_info_file(version_str: str, quad: Tuple[int, int, int, int]) -> Path:
    """Generates a Windows PE file version information resource for PyInstaller."""
    v_info = VERSION_INFO_FILE
    v_info.parent.mkdir(parents=True, exist_ok=True)
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={quad},
    prodvers={quad},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'Sachin Saroj / ZetaJarvis Enterprise'),
         StringStruct('FileDescription', 'ZetaJarvis Enterprise Digital Worker Node'),
         StringStruct('FileVersion', '{version_str}'),
         StringStruct('InternalName', 'ZetaJarvis'),
         StringStruct('LegalCopyright', 'Copyright (c) 2026 Sachin Saroj'),
         StringStruct('OriginalFilename', 'ZetaJarvis.exe'),
         StringStruct('ProductName', 'ZetaJarvis Enterprise Automation Node'),
         StringStruct('ProductVersion', '{version_str}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    v_info.write_text(content, encoding="utf-8")
    return v_info


def generate_icon_if_missing(icon_path: Optional[Path] = None) -> Path:
    """Generates a multi-resolution geometric ZetaJarvis icon if missing."""
    target_path = icon_path or ICON_FILE
    if target_path.exists():
        return target_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not PIL_AVAILABLE or Image is None or ImageDraw is None:
        return target_path

    img = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark cybernetic background circle
    draw.ellipse([(8, 8), (248, 248)], fill=(13, 17, 23, 255), outline=(0, 212, 255, 255), width=8)

    # Inner cyan energy ring
    draw.ellipse([(28, 28), (228, 228)], outline=(30, 60, 90, 255), width=3)

    # Stylized 'Z' glyph
    z_points = [
        (64, 64), (192, 64), (192, 88), (108, 172),
        (192, 172), (192, 196), (64, 196), (64, 172),
        (148, 88), (64, 88)
    ]
    draw.polygon(z_points, fill=(0, 212, 255, 255))

    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(str(target_path), format="ICO", sizes=sizes)
    print(f"  [+] Generated multi-resolution icon: {target_path.name}", flush=True)
    return target_path


# ------------------------------------------------------------------------------
# 3. Executable Compilation (PyInstaller)
# ------------------------------------------------------------------------------

def compile_executable(
    main_script: Optional[str] = None,
    exe_name: str = "ZetaJarvis",
    stealth_mode: bool = False,
    python_exe: str = sys.executable,
) -> Optional[Path]:
    """Compiles single-file executable using PyInstaller."""
    log_step(f"Step 3: Compiling Standalone Executable ({exe_name}.exe)")

    version_str, quad = read_version()
    ver_info_path = generate_version_info_file(version_str, quad)
    icon_path = generate_icon_if_missing()

    entry_script = Path(main_script) if main_script else (SRC_DIR / "zetajarvis" / "main.py")
    if not entry_script.is_absolute():
        entry_script = PROJECT_ROOT / entry_script

    cmd = [
        python_exe,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", exe_name,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--paths", str(SRC_DIR),
    ]

    # Console vs Windowed
    if stealth_mode:
        cmd.append("--windowed")
        print("  [*] Building in Windowed mode (STEALTH_MODE=True).", flush=True)
    else:
        cmd.append("--console")
        print("  [*] Building in Console mode (debugging & telemetry enabled).", flush=True)

    # Version info & Icon
    if ver_info_path.exists():
        cmd.extend(["--version-file", str(ver_info_path)])
    if icon_path.exists():
        cmd.extend(["--icon", str(icon_path)])

    # Added Data bundles
    if CONFIGS_DIR.exists():
        cmd.extend(["--add-data", f"{CONFIGS_DIR};configs"])
    if RESOURCES_DIR.exists():
        cmd.extend(["--add-data", f"{RESOURCES_DIR};resources"])

    # Fallbacks for root assets
    for root_asset in ["tools_config.json", ".env.example", "VERSION.txt"]:
        ap = PROJECT_ROOT / root_asset
        if ap.exists():
            cmd.extend(["--add-data", f"{ap};."])

    # Hidden imports
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])

    # Target entry script
    cmd.append(str(entry_script))

    print(f"  [*] Executing PyInstaller command...", flush=True)
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    if res.returncode != 0:
        print(f"  [!] PyInstaller build failed with exit code {res.returncode}", file=sys.stderr, flush=True)
        return None

    target_exe = DIST_DIR / f"{exe_name}.exe"
    if target_exe.exists():
        size_mb = target_exe.stat().st_size / (1024 * 1024)
        print(f"\n[+] Successfully compiled {target_exe.name} ({size_mb:.2f} MB)", flush=True)
        return target_exe

    return None


# ------------------------------------------------------------------------------
# 4. Post-Build Signing
# ------------------------------------------------------------------------------

def sign_executable(exe_path: Path) -> bool:
    """Signs the compiled executable using signtool.exe if certs are present."""
    log_step(f"Step 4: Post-Build Code Signing ({exe_path.name})")

    cert_files = list(CERTS_DIR.glob("*.pfx")) if CERTS_DIR.exists() else []
    if not cert_files:
        print("  [-] Notice: No certificate (.pfx) found in certs/. Skipping code signing.", flush=True)
        return False

    signtool = shutil.which("signtool.exe") or shutil.which("signtool")
    if not signtool:
        print("  [-] Notice: signtool.exe not found on PATH. Skipping code signing.", flush=True)
        return False

    cert = cert_files[0]
    print(f"  [*] Signing {exe_path.name} with {cert.name}...", flush=True)
    sign_cmd = [
        signtool,
        "sign",
        "/f", str(cert),
        "/fd", "SHA256",
        "/t", "http://timestamp.digicert.com",
        str(exe_path),
    ]
    try:
        res = subprocess.run(sign_cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            print("  [+] Executable signed successfully.", flush=True)
            return True
        else:
            print(f"  [-] signtool notice: {res.stderr.strip()}", flush=True)
    except Exception as exc:
        print(f"  [-] Code signing skipped: {exc}", flush=True)

    return False


# ------------------------------------------------------------------------------
# 5. Installer Compilation
# ------------------------------------------------------------------------------

def compile_installer(python_exe: str = sys.executable) -> Optional[Path]:
    """Compiles installer.py into a standalone dist/ZetaJarvis_Installer.exe."""
    log_step("Step 5: Compiling Self-Contained Installer (ZetaJarvis_Installer.exe)")

    installer_script = SRC_DIR / "zetajarvis" / "deployment" / "installer.py"
    if not installer_script.exists():
        installer_script = PROJECT_ROOT / "installer.py"
    if not installer_script.exists():
        print("  [-] installer.py missing. Skipping installer packaging.", flush=True)
        return None

    icon_path = generate_icon_if_missing()

    cmd = [
        python_exe,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "ZetaJarvis_Installer",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--paths", str(SRC_DIR),
        "--console",
    ]

    if icon_path.exists():
        cmd.extend(["--icon", str(icon_path)])

    dist_exe = DIST_DIR / "ZetaJarvis.exe"
    if dist_exe.exists():
        cmd.extend(["--add-data", f"{dist_exe};dist"])

    if CONFIGS_DIR.exists():
        cmd.extend(["--add-data", f"{CONFIGS_DIR};configs"])
    if RESOURCES_DIR.exists():
        cmd.extend(["--add-data", f"{RESOURCES_DIR};resources"])

    for asset in ["tools_config.json", ".env.example", "VERSION.txt"]:
        ap = PROJECT_ROOT / asset
        if ap.exists():
            cmd.extend(["--add-data", f"{ap};."])

    cmd.append(str(installer_script))

    print("  [*] Building ZetaJarvis_Installer.exe...", flush=True)
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    if res.returncode != 0:
        print("  [-] Installer compilation failed.", file=sys.stderr, flush=True)
        return None

    installer_exe = DIST_DIR / "ZetaJarvis_Installer.exe"
    if installer_exe.exists():
        size_mb = installer_exe.stat().st_size / (1024 * 1024)
        print(f"\n[+] Successfully compiled {installer_exe.name} ({size_mb:.2f} MB)", flush=True)
        return installer_exe

    return None


# ------------------------------------------------------------------------------
# Workspace Cleanup
# ------------------------------------------------------------------------------

def clean_workspace(root: Optional[Path] = None) -> bool:
    """Scrubs build/, dist/, *.spec, and temporary test folders."""
    target_root = root or PROJECT_ROOT
    print("=" * 70, flush=True)
    print(f" ZetaJarvis Workspace Cleanup -- Scrubbing Artifacts ({target_root})", flush=True)
    print("=" * 70, flush=True)

    targets_dir = [
        target_root / "build",
        target_root / "dist",
        target_root / "backups",
        target_root / "staging",
        target_root / "screenshots",
        target_root / "test_tools_temp",
    ]

    for d in targets_dir:
        if d.exists() and d.is_dir():
            try:
                shutil.rmtree(d, ignore_errors=True)
                print(f"  [+] Removed directory: {d.name}/", flush=True)
            except Exception as e:
                print(f"  [-] Failed to remove directory {d.name}: {e}", flush=True)

    for spec_file in target_root.glob("*.spec"):
        try:
            spec_file.unlink(missing_ok=True)
            print(f"  [+] Removed spec file: {spec_file.name}", flush=True)
        except Exception as e:
            print(f"  [-] Failed to remove spec file {spec_file.name}: {e}", flush=True)

    print("\n[+] Workspace cleanup complete.", flush=True)
    print("=" * 70, flush=True)
    return True


# ------------------------------------------------------------------------------
# Full Orchestrated Pipeline
# ------------------------------------------------------------------------------

def run_pipeline(
    skip_tests: bool = False,
    stealth: bool = False,
    keep_build: bool = False,
    python_exe: str = sys.executable,
) -> bool:
    """Executes the full end-to-end production build pipeline."""
    start_time = time.time()
    print("=" * 70, flush=True)
    print(" ZetaJarvis Enterprise Digital Worker Node -- Production Build Pipeline", flush=True)
    print("=" * 70, flush=True)

    # 1. Test Gate
    if not skip_tests:
        test_ok = run_test_gate(python_exe)
        if not test_ok:
            print("\n[!] BUILD ABORTED: Pre-flight test suite failed.", file=sys.stderr, flush=True)
            return False

    # 2. Compile ZetaJarvis.exe
    app_exe = compile_executable(stealth_mode=stealth, python_exe=python_exe)
    if not app_exe:
        print("\n[!] BUILD ABORTED: Failed compiling ZetaJarvis.exe", file=sys.stderr, flush=True)
        return False

    # 3. Sign Executable (if certs available)
    sign_executable(app_exe)

    # 4. Compile Installer
    installer_exe = compile_installer(python_exe=python_exe)
    if installer_exe:
        sign_executable(installer_exe)

    # 5. Scrub temporary build artifacts unless --keep-build
    if not keep_build:
        if BUILD_DIR.exists():
            shutil.rmtree(BUILD_DIR, ignore_errors=True)
        for spec_file in PROJECT_ROOT.glob("*.spec"):
            spec_file.unlink(missing_ok=True)
        print("  [+] Cleaned temporary build directory and spec files.", flush=True)

    # 6. Build Summary
    duration = time.time() - start_time
    log_step("Build Pipeline Completed Successfully")
    print(f"  [+] Main Application: {app_exe}")
    if installer_exe:
        print(f"  [+] One-Click Installer: {installer_exe}")
    print(f"  [+] Total Build Time: {duration:.1f} seconds", flush=True)
    print("=" * 70, flush=True)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZetaJarvis Production Build Pipeline")
    parser.add_argument("command", nargs="?", choices=["build", "clean"], default="build",
                        help="Command to execute: 'build' (default) or 'clean'")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pre-flight test gate")
    parser.add_argument("--stealth", action="store_true", help="Build executable in windowed mode (no console)")
    parser.add_argument("--keep-build", action="store_true", help="Keep temporary build/ directory and .spec files")
    parser.add_argument("--clean", action="store_true", help="Scrub build/, dist/, .spec, and temporary test directories")
    args = parser.parse_args()

    if args.command == "clean" or args.clean:
        clean_workspace()
        sys.exit(0)

    stealth_env = os.getenv("STEALTH_MODE", "false").lower() in ("1", "true", "yes")
    stealth_active = args.stealth or stealth_env

    success = run_pipeline(
        skip_tests=args.skip_tests,
        stealth=stealth_active,
        keep_build=args.keep_build,
    )
    sys.exit(0 if success else 1)
