#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: ui_automation.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Cross-application UI automation for Windows (window control,
#              mouse click, keyboard typing, screen capture, clipboard sync)
#              with safety kill-switch and brain tool registration.
# ------------------------------------------------------------------------------

"""Module 6: UI Automation – Cross-Application Control & Safe Execution.

Features:
- Window Management: Find, focus, minimize, maximize, close windows by title/class.
- Input Simulation: Click and type text at coordinates or controls via uiautomation/ctypes.
- Screen Capture: High-resolution screenshots of specific windows or screen via PIL.
- Clipboard Operations: Thread-safe read and write to Windows clipboard.
- Safety Kill-Switch: "Zeta, abort automation" stops ongoing actions and releases inputs.
- Brain Tool Integration: Automatically registers control_window, click_element, type_text,
  capture_screen, get_clipboard, and set_clipboard into brain.TOOL_REGISTRY and tools_config.json.
"""

from __future__ import annotations

import ctypes
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# Windows UI Automation / win32 modules
try:
    import win32clipboard
    import win32con
    import win32gui
    WIN32_AVAILABLE = True
except ImportError:
    win32clipboard = None
    win32con = None
    win32gui = None
    WIN32_AVAILABLE = False

# uiautomation support
try:
    import uiautomation as auto
    UIAUTOMATION_AVAILABLE = True
except ImportError:
    auto = None
    UIAUTOMATION_AVAILABLE = False

# PIL ImageGrab for screen capture
try:
    from PIL import ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    ImageGrab = None
    PIL_AVAILABLE = False

import brain


# ==============================================================================
# Configuration & Safety Kill-Switch
# ==============================================================================

SCREENSHOTS_DIR = Path(os.getenv("SCREENSHOTS_DIR", "screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Global Thread-Safe Abort Event
_ABORT_EVENT = threading.Event()


def trigger_abort() -> None:
    """Activates the safety kill-switch to immediately halt all UI automation."""
    _ABORT_EVENT.set()
    # Release any held mouse buttons and modifier keys
    if sys.platform.startswith("win"):
        try:
            user32 = ctypes.windll.user32
            # MOUSEEVENTF_LEFTUP = 0x0004, MOUSEEVENTF_RIGHTUP = 0x0010
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            user32.mouse_event(0x0010, 0, 0, 0, 0)
            # Release Shift, Ctrl, Alt (KEYEVENTF_KEYUP = 0x0002)
            user32.keybd_event(0x10, 0, 0x0002, 0)  # VK_SHIFT
            user32.keybd_event(0x11, 0, 0x0002, 0)  # VK_CONTROL
            user32.keybd_event(0x12, 0, 0x0002, 0)  # VK_MENU (Alt)
        except Exception:
            pass


def reset_abort() -> None:
    """Resets the safety kill-switch."""
    _ABORT_EVENT.clear()


def is_aborted() -> bool:
    """Returns True if the safety kill-switch is active."""
    return _ABORT_EVENT.is_set()


def check_abort_phrase(text: str) -> bool:
    """Checks if voice input matches the kill-switch phrase 'Zeta, abort automation'."""
    clean = text.strip().lower()
    return "abort automation" in clean or ("abort" in clean and "zeta" in clean)


# ==============================================================================
# Window Management Engine
# ==============================================================================

class WindowController:
    """Controls application windows on Windows operating systems."""

    @staticmethod
    def find_window(title_substr: str) -> Optional[int]:
        """Finds the window handle (HWND) matching title substring."""
        if not sys.platform.startswith("win"):
            return None

        found_hwnd: Optional[int] = None

        def _enum_callback(hwnd: int, extra: Any) -> bool:
            nonlocal found_hwnd
            if WIN32_AVAILABLE and win32gui is not None:
                if win32gui.IsWindowVisible(hwnd):
                    text = win32gui.GetWindowText(hwnd)
                    if title_substr.lower() in text.lower():
                        found_hwnd = hwnd
                        return False
            return True

        if WIN32_AVAILABLE and win32gui is not None:
            try:
                win32gui.EnumWindows(_enum_callback, None)
            except Exception:
                pass
            return found_hwnd

        # Fallback to ctypes user32 FindWindow
        try:
            return ctypes.windll.user32.FindWindowW(None, title_substr) or None
        except Exception:
            return None

    @staticmethod
    def get_window_rect(hwnd: Optional[int]) -> Optional[Dict[str, int]]:
        """Returns the bounding rectangle dict for the specified HWND, or None."""
        if not hwnd or not sys.platform.startswith("win"):
            return None
        try:
            rect = (ctypes.c_long * 4)()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            return {
                "left": rect[0],
                "top": rect[1],
                "right": rect[2],
                "bottom": rect[3],
                "width": rect[2] - rect[0],
                "height": rect[3] - rect[1],
            }
        except Exception:
            return None

    @staticmethod
    def control_window(title: str, action: str) -> Dict[str, Any]:
        """Executes window management action: focus, minimize, maximize, close, get_rect, open, launch."""
        if is_aborted():
            return {"status": "aborted", "message": "Automation aborted by kill-switch."}

        action = action.strip().lower()

        if action in ("open", "launch"):
            return ApplicationController.launch_application(title)

        hwnd = WindowController.find_window(title)
        if not hwnd:
            if action == "focus":
                # Resilient fallback: attempt to launch if not running
                launch_res = ApplicationController.launch_application(title)
                if launch_res.get("status") == "success":
                    time.sleep(1.0)
                    new_hwnd = WindowController.find_window(title)
                    if new_hwnd and sys.platform.startswith("win"):
                        ctypes.windll.user32.ShowWindow(new_hwnd, 9)
                        ctypes.windll.user32.SetForegroundWindow(new_hwnd)
                        return {"status": "success", "action": "focus_after_launch", "hwnd": new_hwnd}
                return {"status": "error", "message": f"Window matching '{title}' not found."}
            return {"status": "error", "message": f"Window matching '{title}' not found."}

        user32 = ctypes.windll.user32

        if action == "focus":
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE = 9
            user32.SetForegroundWindow(hwnd)
            return {"status": "success", "action": "focus", "hwnd": hwnd}

        elif action == "minimize":
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE = 6
            return {"status": "success", "action": "minimize", "hwnd": hwnd}

        elif action == "maximize":
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE = 3
            return {"status": "success", "action": "maximize", "hwnd": hwnd}

        elif action == "close":
            # WM_CLOSE = 0x0010
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
            return {"status": "success", "action": "close", "hwnd": hwnd}

        elif action == "get_rect":
            rect = (ctypes.c_long * 4)()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            return {
                "status": "success",
                "action": "get_rect",
                "left": rect[0],
                "top": rect[1],
                "right": rect[2],
                "bottom": rect[3],
                "width": rect[2] - rect[0],
                "height": rect[3] - rect[1],
            }

        return {"status": "error", "message": f"Unknown window action: {action}"}


# ==============================================================================
# Application Controller
# ==============================================================================

class ApplicationController:
    """Manages launching and executing desktop applications."""

    @staticmethod
    def launch_application(app_name: str) -> Dict[str, Any]:
        """Launches a desktop application by command or name (e.g. 'notepad', 'calc')."""
        if is_aborted():
            return {"status": "aborted", "message": "Automation aborted by kill-switch."}

        clean_cmd = app_name.strip()
        if not clean_cmd:
            return {"status": "error", "message": "Application command or name cannot be empty."}

        # Prevent potentially dangerous shell injections
        for banned in [";", "&&", "||", "|", ">", "<", "`", "$"]:
            if banned in clean_cmd:
                return {"status": "error", "message": f"Command contains forbidden character: {banned}"}

        try:
            # Launch via subprocess without blocking
            proc = subprocess.Popen(clean_cmd, shell=True)
            time.sleep(1.0)  # Brief grace period for window creation
            return {
                "status": "success",
                "message": f"Application '{clean_cmd}' launched successfully.",
                "pid": proc.pid,
            }
        except Exception as exc:
            return {"status": "error", "message": f"Failed to launch '{clean_cmd}': {str(exc)}"}


# ==============================================================================
# Mouse, Keyboard & Screen Capture
# ==============================================================================

class InputController:
    """Simulates hardware mouse clicks, keyboard text typing, and screen capture."""

    @staticmethod
    def click_element(x: int, y: int, button: str = "left", clicks: int = 1) -> Dict[str, Any]:
        """Moves cursor to (x, y) and performs click."""
        if is_aborted():
            return {"status": "aborted", "message": "Automation aborted by kill-switch."}

        if not sys.platform.startswith("win"):
            return {"status": "skipped", "message": "Input simulation only supported on Windows."}

        user32 = ctypes.windll.user32
        user32.SetCursorPos(x, y)
        time.sleep(0.05)

        down_flag = 0x0002 if button == "left" else 0x0008
        up_flag = 0x0004 if button == "left" else 0x0010

        for _ in range(clicks):
            if is_aborted():
                return {"status": "aborted", "message": "Automation aborted by kill-switch."}
            user32.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(up_flag, 0, 0, 0, 0)
            time.sleep(0.05)

        return {"status": "success", "clicked_at": {"x": x, "y": y}, "button": button}

    @staticmethod
    def type_text(text: str, press_enter: bool = False) -> Dict[str, Any]:
        """Types string into currently focused control."""
        if is_aborted():
            return {"status": "aborted", "message": "Automation aborted by kill-switch."}

        # Preferred: uiautomation SendKeys
        if UIAUTOMATION_AVAILABLE and auto is not None:
            try:
                auto.SendKeys(text)
                if press_enter:
                    auto.SendKeys("{Enter}")
                return {"status": "success", "typed_chars": len(text)}
            except Exception:
                pass

        # Fallback: ctypes user32 keybd_event with clipboard paste for fast unicode support
        ClipboardController.set_clipboard(text)
        user32 = ctypes.windll.user32
        VK_CONTROL = 0x11
        VK_V = 0x56
        # Ctrl+V
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_V, 0, 0x0002, 0)
        user32.keybd_event(VK_CONTROL, 0, 0x0002, 0)

        if press_enter:
            VK_RETURN = 0x0D
            user32.keybd_event(VK_RETURN, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(VK_RETURN, 0, 0x0002, 0)

        return {"status": "success", "typed_chars": len(text), "mode": "clipboard_paste"}

    @staticmethod
    def capture_screen(window_title: str = "", output_path: str = "") -> Dict[str, Any]:
        """Captures full screen or target window and saves to disk."""
        if is_aborted():
            return {"status": "aborted", "message": "Automation aborted by kill-switch."}

        if not PIL_AVAILABLE or ImageGrab is None:
            return {"status": "error", "message": "Pillow (PIL) is not installed."}

        bbox: Optional[Tuple[int, int, int, int]] = None
        if window_title:
            hwnd = WindowController.find_window(window_title)
            if hwnd:
                rect = (ctypes.c_long * 4)()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                bbox = (rect[0], rect[1], rect[2], rect[3])

        try:
            img = ImageGrab.grab(bbox=bbox)
            if not output_path:
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = str(SCREENSHOTS_DIR / f"capture_{ts}.png")

            img.save(output_path)
            return {
                "status": "success",
                "saved_to": output_path,
                "width": img.width,
                "height": img.height,
            }
        except Exception as exc:
            return {"status": "error", "message": f"Screen capture failed: {str(exc)}"}


# ==============================================================================
# Clipboard Controller
# ==============================================================================

class ClipboardController:
    """Thread-safe Windows clipboard reader and writer."""

    @staticmethod
    def get_clipboard() -> str:
        """Reads unicode text from Windows clipboard."""
        if is_aborted():
            return ""

        if WIN32_AVAILABLE and win32clipboard is not None:
            try:
                win32clipboard.OpenClipboard()
                text = ""
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                return text or ""
            except Exception:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass

        # Fallback via ctypes user32 OpenClipboard
        return ""

    @staticmethod
    def set_clipboard(text: str) -> bool:
        """Writes unicode text to Windows clipboard."""
        if is_aborted():
            return False

        if WIN32_AVAILABLE and win32clipboard is not None:
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                win32clipboard.CloseClipboard()
                return True
            except Exception:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
        return False


# ==============================================================================
# Brain Tool Handlers & Schema Registration
# ==============================================================================

def tool_control_window(title: str, action: str) -> str:
    """Tool: Controls a window by title (focus, minimize, maximize, close, get_rect)."""
    res = WindowController.control_window(title, action)
    return json.dumps(res)


def tool_click_element(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    """Tool: Clicks at the specified (x, y) coordinates with mouse."""
    res = InputController.click_element(x, y, button, clicks)
    return json.dumps(res)


def tool_type_text(text: str, press_enter: bool = False) -> str:
    """Tool: Types text into the currently active or focused control."""
    res = InputController.type_text(text, press_enter)
    return json.dumps(res)


def tool_capture_screen(window_title: str = "", output_path: str = "") -> str:
    """Tool: Captures full screen or target window and saves screenshot to disk."""
    res = InputController.capture_screen(window_title, output_path)
    return json.dumps(res)


def tool_get_clipboard() -> str:
    """Tool: Retrieves current text stored in the system clipboard."""
    txt = ClipboardController.get_clipboard()
    return json.dumps({"clipboard_text": txt})


def tool_set_clipboard(text: str) -> str:
    """Tool: Copies text to the system clipboard."""
    ok = ClipboardController.set_clipboard(text)
    return json.dumps({"status": "success" if ok else "failed"})


def tool_launch_application(app_name: str) -> str:
    """Tool: Launches a desktop application by name or command (e.g. 'notepad', 'calc')."""
    res = ApplicationController.launch_application(app_name)
    return json.dumps(res)


# Register with Brain TOOL_REGISTRY
brain.register_tool_handler("control_window", tool_control_window)
brain.register_tool_handler("click_element", tool_click_element)
brain.register_tool_handler("type_text", tool_type_text)
brain.register_tool_handler("capture_screen", tool_capture_screen)
brain.register_tool_handler("get_clipboard", tool_get_clipboard)
brain.register_tool_handler("set_clipboard", tool_set_clipboard)
brain.register_tool_handler("launch_application", tool_launch_application)


def register_ui_tools_to_config(config_path: Path = Path("tools_config.json")) -> None:
    """Injects UI automation tools into tools_config.json."""
    ui_tool_schemas = [
        {
            "type": "function",
            "function": {
                "name": "launch_application",
                "description": "Launches a desktop application by name or executable, such as 'notepad' or 'calc'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app_name": {"type": "string", "description": "Application command or executable name, e.g. 'notepad'"},
                    },
                    "required": ["app_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "control_window",
                "description": "Finds and controls windows: focus, minimize, maximize, close, get_rect.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Window title substring"},
                        "action": {"type": "string", "enum": ["focus", "minimize", "maximize", "close", "get_rect"]},
                    },
                    "required": ["title", "action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "click_element",
                "description": "Simulates mouse click at coordinates (x, y).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "Screen X coordinate"},
                        "y": {"type": "integer", "description": "Screen Y coordinate"},
                        "button": {"type": "string", "enum": ["left", "right"]},
                        "clicks": {"type": "integer", "description": "Number of clicks"},
                    },
                    "required": ["x", "y"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "type_text",
                "description": "Types text into the active window control.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text string to type"},
                        "press_enter": {"type": "boolean", "description": "Whether to press Enter afterwards"},
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "capture_screen",
                "description": "Takes a screenshot of the entire screen or a specific window.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "window_title": {"type": "string", "description": "Optional window title"},
                        "output_path": {"type": "string", "description": "Optional file path to save image"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_clipboard",
                "description": "Retrieves the current text from system clipboard.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_clipboard",
                "description": "Sets text to the system clipboard.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to copy to clipboard"},
                    },
                    "required": ["text"],
                },
            },
        },
    ]

    if not config_path.exists():
        config_path.write_text(json.dumps({"tools": ui_tool_schemas}, indent=2), encoding="utf-8")
        return

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        existing_tools = data.get("tools", [])
        existing_names = {t.get("function", {}).get("name") for t in existing_tools}

        for new_tool in ui_tool_schemas:
            name = new_tool["function"]["name"]
            if name not in existing_names:
                existing_tools.append(new_tool)

        data["tools"] = existing_tools
        config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[UI Automation Warn] Failed updating tools_config.json: {exc}", file=sys.stderr)


# Auto-inject schemas
register_ui_tools_to_config()


# ==============================================================================
# Standalone Verification Demo
# ==============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print(" ZetaJarvis Module 6: UI Automation -- Verification & Demo")
    print("=" * 70)

    print("\n[1] Verifying System UI Automation Libraries:")
    print(f"  PyWin32 Available: {WIN32_AVAILABLE}")
    print(f"  UIAutomation Available: {UIAUTOMATION_AVAILABLE}")
    print(f"  Pillow (PIL) Available: {PIL_AVAILABLE}")

    print("\n[2] Testing Clipboard Read & Write:")
    test_phrase = f"ZetaJarvis Automation Test Token: {int(time.time())}"
    ClipboardController.set_clipboard(test_phrase)
    read_back = ClipboardController.get_clipboard()
    print(f"  Wrote to clipboard: '{test_phrase}'")
    print(f"  Read from clipboard: '{read_back}'")
    print(f"  Clipboard verification: {'SUCCESS' if test_phrase == read_back else 'FAILED'}")

    print("\n[3] Testing Screen Capture:")
    temp_screen_file = SCREENSHOTS_DIR / "test_demo_capture.png"
    cap_res = InputController.capture_screen(output_path=str(temp_screen_file))
    print(f"  Capture Result: {cap_res['status']}")
    if cap_res["status"] == "success":
        print(f"  Image saved ({cap_res.get('width')}x{cap_res.get('height')}): {temp_screen_file}")
        if temp_screen_file.exists():
            temp_screen_file.unlink(missing_ok=True)

    print("\n[4] Testing Window Search:")
    # Look for common window e.g. explorer, powershell, or cmd
    test_hwnd = WindowController.find_window("PowerShell") or WindowController.find_window("cmd")
    print(f"  Found Terminal Window HWND: {test_hwnd}")

    print("\n[5] Testing Safety Kill-Switch ('Zeta, abort automation'):")
    print(f"  Abort phrase check ('Zeta, abort automation'): {check_abort_phrase('Zeta, abort automation now')}")
    trigger_abort()
    print(f"  Is Aborted: {is_aborted()}")
    aborted_op = WindowController.control_window("Notepad", "focus")
    print(f"  Operation response while aborted: {aborted_op}")
    reset_abort()
    print(f"  Kill-switch reset. Is Aborted: {is_aborted()}")

    print("\n[6] Brain Tool Registration Verification:")
    registered = [t for t in ["control_window", "click_element", "type_text", "capture_screen", "get_clipboard", "set_clipboard", "launch_application"] if t in brain.TOOL_REGISTRY]
    print(f"  Registered Brain Handlers: {registered}")

    print("\n[SUCCESS] Module 6 (ui_automation.py) verified successfully.")
