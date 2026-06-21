#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: jarvis/winops.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: Windows low-level operations implementation (only invoked on Windows).
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""Windows low-level operations implementation for ZetaJarvis (only invoked on Windows).

ZetaJarvis was originally designed to run cross-platform. This module provides Windows equivalents
using standard libraries, PowerShell, and ctypes, without introducing external dependencies.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile
import time

# Hide PowerShell window on Windows
_NO_WINDOW = 0x08000000


# ---- PowerShell Executor -------------------------------------------------

def powershell(script: str, env: dict | None = None, timeout: float = 60) -> str:
    """Executes a PowerShell script and returns stdout (UTF-8). Returns stderr on failure."""
    full = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;" + script
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", full],
            capture_output=True, env=env, timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return "(Command timed out)"
    out = r.stdout.decode("utf-8", "ignore").strip()
    if not out:
        out = r.stderr.decode("utf-8", "ignore").strip()
    return out


# ---- Clipboard ------------------------------------------------------------

def get_clipboard() -> str:
    return powershell("Get-Clipboard -Raw")


def set_clipboard(text: str) -> None:
    # Pass value via environment variables to avoid quote escaping issues
    powershell("Set-Clipboard -Value $env:JV_CLIP",
               env={**os.environ, "JV_CLIP": text})


# ---- Key Event Simulation (Virtual Key Codes, Media/Volume Control) -------

_VK = {
    "media_play_pause": 0xB3, "media_next": 0xB0, "media_prev": 0xB1,
    "volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
}
_KEYEVENTF_KEYUP = 0x0002


def _tap(vk: int, times: int = 1) -> None:
    user32 = ctypes.windll.user32
    for _ in range(max(1, times)):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)
        time.sleep(0.005)


def media(action: str) -> str:
    """Controls system media playback (applies to active players / browser music)."""
    names = {"play": "Played", "pause": "Paused", "playpause": "Toggled playback of",
             "next": "Skipped to next", "previous": "Skipped to previous"}
    if action in ("play", "pause", "playpause"):
        _tap(_VK["media_play_pause"])
    elif action == "next":
        _tap(_VK["media_next"])
    elif action == "previous":
        _tap(_VK["media_prev"])
    return names.get(action, "Controlled") + " music"


def set_volume(level: int) -> str:
    """Sets system master volume (approximate). Since Windows lacks a direct absolute volume command,
    this function lowers volume to zero first, then taps volume up to target levels (approx 2% per tap)."""
    level = max(0, min(100, int(level)))
    _tap(_VK["volume_down"], 50)          # Set to zero first
    _tap(_VK["volume_up"], round(level / 2))   # Taps up (approx 2% per tap) to reach target
    return f"Volume set to approx {level}%"


# ---- Application / Power -------------------------------------------------------

# Common English app names -> Windows executable names/launch targets
_APP_ALIASES = {
    "whatsapp": "WhatsApp",
    "browser": "msedge", "edge": "msedge", "chrome": "chrome", "safari": "msedge",
    "calculator": "calc", "calc": "calc", "notepad": "notepad", "memo": "notepad",
    "file manager": "explorer", "explorer": "explorer", "finder": "explorer",
    "music": "wmplayer", "player": "wmplayer", "settings": "ms-settings:",
    "task manager": "taskmgr", "taskmgr": "taskmgr", "paint": "mspaint", "mspaint": "mspaint", "terminal": "wt", "wt": "wt",
    "cmd": "cmd", "powershell": "powershell",
}


def open_app(name: str) -> str:
    target = _APP_ALIASES.get(name.strip().lower(), name)
    try:
        # cmd start can run executables on PATH, registered apps, or protocols
        subprocess.run(["cmd", "/c", "start", "", target],
                       creationflags=_NO_WINDOW, timeout=10)
        return f"Opened {name}"
    except Exception:  # noqa: BLE001
        return f"Application not found: \"{name}\""


def lock() -> None:
    ctypes.windll.user32.LockWorkStation()


def sleep_pc() -> None:
    # Suspends system to sleep (or hibernate if sleep is disabled)
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                   creationflags=_NO_WINDOW)


# ---- Recycle Bin (Safer than rm/del, can be restored) -------------------------

def recycle(path: str) -> str:
    """Moves a file or directory to the Recycle Bin. Returns empty string on success, else returns error."""
    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic;"
        "$p=$env:JV_PATH;"
        "if(Test-Path -LiteralPath $p -PathType Container){"
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
        "$p,'OnlyErrorDialogs','SendToRecycleBin')}"
        "else{[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
        "$p,'OnlyErrorDialogs','SendToRecycleBin')}"
    )
    return powershell(script, env={**os.environ, "JV_PATH": path})


# ---- WhatsApp Message (UI Automation) ----------------------------------------

def send_whatsapp(contact: str, message: str) -> str:
    """Activate WhatsApp Desktop -> Ctrl+F search contact -> Enter to conversation -> Paste message -> Enter to send.
    Requires WhatsApp Desktop to be open and logged in. Uses clipboard paste for reliability; restores clipboard afterward."""
    saved = get_clipboard()
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$w=New-Object -ComObject WScript.Shell;"
        "if(-not $w.AppActivate('WhatsApp')){"
        "  Write-Output 'ERROR: WhatsApp Desktop window not found. Please make sure the app is open and running.';"
        "  exit;"
        "};"
        "Start-Sleep -Milliseconds 800;"
        "[System.Windows.Forms.SendKeys]::SendWait('^f');"
        "Start-Sleep -Milliseconds 500;"
        "Set-Clipboard -Value $env:JV_CONTACT;"
        "[System.Windows.Forms.SendKeys]::SendWait('^v');"
        "Start-Sleep -Milliseconds 1200;"
        "[System.Windows.Forms.SendKeys]::SendWait('{ENTER}');"
        "Start-Sleep -Milliseconds 800;"
        "Set-Clipboard -Value $env:JV_MSG;"
        "[System.Windows.Forms.SendKeys]::SendWait('^v');"
        "Start-Sleep -Milliseconds 500;"
        "[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')"
    )
    try:
        out = powershell(script, env={**os.environ,
                                     "JV_CONTACT": contact, "JV_MSG": message})
        if "ERROR:" in out:
            return out
        return f"Attempted to send WhatsApp message to \"{contact}\" via UI automation: {message}"
    finally:
        time.sleep(0.3)
        set_clipboard(saved)


# ---- System Telemetry (For Desktop Pet HUD) ------------------------------------

def boot_epoch() -> float:
    """System boot time (Unix timestamp). Calculated from GetTickCount64 (ms)."""
    tick_ms = ctypes.windll.kernel32.GetTickCount64()
    return time.time() - tick_ms / 1000.0


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def battery() -> tuple[int | None, bool]:
    """Returns (battery percentage or None, whether charging)."""
    status = _SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None, False
    pct = status.BatteryLifePercent
    pct = None if pct == 255 else int(pct)           # 255 = unknown/no battery
    charging = status.ACLineStatus == 1
    return pct, charging


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    @property
    def value(self) -> int:
        return (self.high << 32) | self.low


class CpuSampler:
    """Calculates CPU utilization (0.0 to 1.0) using two samples of GetSystemTimes."""

    def __init__(self) -> None:
        self._prev: tuple[int, int, int] | None = None

    def _read(self) -> tuple[int, int, int]:
        idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
        ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        return idle.value, kernel.value, user.value

    def percent(self) -> float:
        try:
            idle, kernel, user = self._read()
        except Exception:  # noqa: BLE001
            return 0.0
        if self._prev is None:
            self._prev = (idle, kernel, user)
            return 0.0
        pi, pk, pu = self._prev
        self._prev = (idle, kernel, user)
        total = (kernel - pk) + (user - pu)   # kernel time already includes idle time
        if total <= 0:
            return 0.0
        busy = total - (idle - pi)
        return max(0.0, min(1.0, busy / total))
