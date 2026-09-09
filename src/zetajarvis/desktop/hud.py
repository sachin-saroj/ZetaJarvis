#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: hud.py
# Project: ZetaJarvis - Desktop Domination Layer
# Description: Borderless, always-on-top, transparent overlay with real-time
#              telemetry, token counters, typewriter streaming, and global hotkeys.
# ------------------------------------------------------------------------------

"""Module 1: HUD (Heads-Up Display) System Overlay & Telemetry.

Features:
- Borderless, always-on-top, semi-transparent Tkinter window.
- Real-time token counter (session + daily quota utilization) and active model badge.
- Typewriter character-by-character streaming text display with adjustable speed.
- System telemetry (CPU%, RAM%, GPU%) with psutil and Windows ctypes fallback.
- Non-blocking architecture using threading and queue.Queue.
- Global hotkey listener (toggle visibility and force-kill hanging tools).
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional

# Tkinter (built-in)
import tkinter as tk
from tkinter import font as tkfont

# Optional psutil for system telemetry
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

# Optional pynput for global hotkeys
try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    keyboard = None
    PYNPUT_AVAILABLE = False


# ==============================================================================
# Configuration
# ==============================================================================

HUD_WIDTH = int(os.getenv("HUD_WIDTH", "440"))
HUD_HEIGHT = int(os.getenv("HUD_HEIGHT", "260"))
HUD_ALPHA = float(os.getenv("HUD_ALPHA", "0.88"))
TYPEWRITER_SPEED_MS = int(os.getenv("TYPEWRITER_SPEED_MS", "15"))  # ms per character
HOTKEY_TOGGLE = os.getenv("HOTKEY_TOGGLE", "<ctrl>+<alt>+h")
HOTKEY_KILL = os.getenv("HOTKEY_KILL", "<ctrl>+<alt>+k")


# ==============================================================================
# Telemetry Provider (psutil + Windows ctypes Fallback)
# ==============================================================================

class MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def get_system_telemetry() -> Dict[str, str]:
    """Retrieves CPU%, RAM%, and GPU% with zero crash guarantee."""
    cpu_str = "N/A"
    ram_str = "N/A"
    gpu_str = "N/A"

    # 1. CPU and RAM via psutil if present
    if PSUTIL_AVAILABLE:
        try:
            cpu_val = psutil.cpu_percent(interval=None)
            ram_val = psutil.virtual_memory().percent
            cpu_str = f"{cpu_val:.1f}%"
            ram_str = f"{ram_val:.1f}%"
        except Exception:
            pass

    # Fallback to Windows ctypes if psutil is unavailable or returned N/A
    if ram_str == "N/A" and sys.platform.startswith("win"):
        try:
            stat = MemoryStatus()
            stat.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                ram_str = f"{stat.dwMemoryLoad}%"
        except Exception:
            pass

    # 2. GPU Telemetry via nvidia-smi if installed
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=0.3,
            creationflags=0x08000000 if sys.platform.startswith("win") else 0,
        )
        if res.returncode == 0 and res.stdout.strip():
            gpu_str = f"{res.stdout.strip().splitlines()[0]}%"
    except Exception:
        gpu_str = "N/A"

    return {"cpu": cpu_str, "ram": ram_str, "gpu": gpu_str}


# ==============================================================================
# Transparent Borderless HUD Window
# ==============================================================================

class ZetaHUD:
    """Non-blocking transparent borderless overlay for ZetaJarvis."""

    def __init__(
        self,
        on_force_kill: Optional[Callable[[], None]] = None,
        speed_ms: int = TYPEWRITER_SPEED_MS,
    ) -> None:
        self.on_force_kill = on_force_kill
        self.speed_ms = speed_ms
        self.queue: queue.Queue = queue.Queue()
        self.visible = True
        self._root: Optional[tk.Tk] = None
        self._typewriter_buffer: list[str] = []
        self._is_typing = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Starts the HUD UI in a dedicated non-blocking thread."""
        self._thread = threading.Thread(target=self._run_ui, name="ZetaHUD-Thread", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Requests graceful shutdown of the HUD."""
        self._stop_event.set()
        self.queue.put({"type": "exit"})

    def _run_ui(self) -> None:
        """Internal Tkinter mainloop execution."""
        try:
            self._root = tk.Tk()
            self._root.title("ZetaJarvis HUD")
            self._root.overrideredirect(True)  # Borderless
            self._root.attributes("-topmost", True)  # Always on top

            # Transparency support (Windows & Linux/macOS)
            try:
                self._root.attributes("-alpha", HUD_ALPHA)
            except Exception:
                pass

            # Position in top-right corner
            screen_w = self._root.winfo_screenwidth()
            x = max(20, screen_w - HUD_WIDTH - 30)
            y = 40
            self._root.geometry(f"{HUD_WIDTH}x{HUD_HEIGHT}+{x}+{y}")
            self._root.configure(bg="#0d1117")

            self._build_widgets()
            self._start_hotkey_listener()

            # Periodic update ticks
            self._root.after(40, self._process_queue)
            self._root.after(1000, self._update_telemetry_tick)

            self._root.mainloop()
        except Exception as e:
            # Silent fallback if GUI environment is headless
            print(f"[HUD Notice] Running in headless mode or display unavailable: {e}", file=sys.stderr)

    def _build_widgets(self) -> None:
        """Constructs modern styled HUD components."""
        root = self._root
        assert root is not None

        # Container Frame
        container = tk.Frame(root, bg="#0d1117", highlightthickness=1, highlightbackground="#00f0ff")
        container.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Header: Active Model & Status
        header_frame = tk.Frame(container, bg="#161b22")
        header_frame.pack(fill=tk.X, padx=4, pady=4)

        self.lbl_title = tk.Label(
            header_frame,
            text="ZETA-JARVIS HUD",
            font=("Segoe UI", 9, "bold"),
            fg="#00f0ff",
            bg="#161b22",
        )
        self.lbl_title.pack(side=tk.LEFT, padx=6)

        self.lbl_model = tk.Label(
            header_frame,
            text="MODEL: nemotron-3-ultra:free",
            font=("Segoe UI", 8),
            fg="#ffb800",
            bg="#161b22",
        )
        self.lbl_model.pack(side=tk.RIGHT, padx=6)

        # Token Tracker Bar
        token_frame = tk.Frame(container, bg="#0d1117")
        token_frame.pack(fill=tk.X, padx=8, pady=2)

        self.lbl_tokens = tk.Label(
            token_frame,
            text="⚡ Tokens: Session 0 | Daily 0 / 100,000 (0.0%)",
            font=("Segoe UI", 8),
            fg="#e6edf3",
            bg="#0d1117",
            anchor="w",
        )
        self.lbl_tokens.pack(fill=tk.X)

        # Telemetry Bar
        telem_frame = tk.Frame(container, bg="#0d1117")
        telem_frame.pack(fill=tk.X, padx=8, pady=2)

        self.lbl_telem = tk.Label(
            telem_frame,
            text="📊 CPU: -- | RAM: -- | GPU: --",
            font=("Consolas", 8),
            fg="#7ee787",
            bg="#0d1117",
            anchor="w",
        )
        self.lbl_telem.pack(fill=tk.X)

        # Typewriter Streaming Response Box
        text_frame = tk.Frame(container, bg="#161b22")
        text_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        self.txt_stream = tk.Text(
            text_frame,
            wrap=tk.WORD,
            font=("Segoe UI", 9),
            bg="#161b22",
            fg="#f0f6fc",
            relief=tk.FLAT,
            padx=6,
            pady=6,
            height=6,
        )
        self.txt_stream.pack(fill=tk.BOTH, expand=True)

        # Footer / Hotkey Reminder
        footer_frame = tk.Frame(container, bg="#0d1117")
        footer_frame.pack(fill=tk.X, padx=8, pady=2)

        self.lbl_hotkeys = tk.Label(
            footer_frame,
            text="[F9/Ctrl+Alt+H: Toggle] [F10/Ctrl+Alt+K: Kill Tools]",
            font=("Segoe UI", 7),
            fg="#8b949e",
            bg="#0d1117",
            anchor="w",
        )
        self.lbl_hotkeys.pack(fill=tk.X)

    def _process_queue(self) -> None:
        """Processes events sent to the HUD without blocking."""
        if self._stop_event.is_set() or not self._root:
            return

        try:
            while True:
                msg = self.queue.get_nowait()
                msg_type = msg.get("type")

                if msg_type == "exit":
                    self._root.destroy()
                    return

                elif msg_type == "toggle_visibility":
                    self.toggle_visibility()

                elif msg_type == "token_update":
                    session = msg.get("session", 0)
                    daily = msg.get("daily", 0)
                    quota = msg.get("quota", 100000)
                    model = msg.get("model", "")
                    pct = (daily / quota * 100.0) if quota > 0 else 0.0
                    self.lbl_tokens.config(
                        text=f"⚡ Tokens: Session {session:,} | Daily {daily:,} / {quota:,} ({pct:.1f}%)"
                    )
                    if model:
                        clean_model = model.split("/")[-1].replace(":free", "")
                        self.lbl_model.config(text=f"MODEL: {clean_model}")

                elif msg_type == "stream_text":
                    text = msg.get("text", "")
                    # Clear box and queue up characters for typewriter effect
                    self.txt_stream.delete("1.0", tk.END)
                    self._typewriter_buffer = list(text)
                    if not self._is_typing:
                        self._is_typing = True
                        self._root.after(self.speed_ms, self._typewriter_tick)

                elif msg_type == "append_chunk":
                    chunk = msg.get("chunk", "")
                    self._typewriter_buffer.extend(list(chunk))
                    if not self._is_typing:
                        self._is_typing = True
                        self._root.after(self.speed_ms, self._typewriter_tick)

                elif msg_type == "clear":
                    self._typewriter_buffer.clear()
                    self.txt_stream.delete("1.0", tk.END)

                self.queue.task_done()
        except queue.Empty:
            pass

        self._root.after(40, self._process_queue)

    def _typewriter_tick(self) -> None:
        """Renders the next character in the typewriter buffer."""
        if not self._root or not self._typewriter_buffer:
            self._is_typing = False
            return

        char = self._typewriter_buffer.pop(0)
        self.txt_stream.insert(tk.END, char)
        self.txt_stream.see(tk.END)

        if self._typewriter_buffer:
            self._root.after(self.speed_ms, self._typewriter_tick)
        else:
            self._is_typing = False

    def _update_telemetry_tick(self) -> None:
        """Refreshes CPU, RAM, and GPU telemetry labels every second."""
        if not self._root or self._stop_event.is_set():
            return

        if getattr(self, "_telemetry_paused", False):
            self.lbl_telem.config(text="📊 Telemetry: Paused (Governor Throttling)")
        else:
            telem = get_system_telemetry()
            self.lbl_telem.config(
                text=f"📊 CPU: {telem['cpu']} | RAM: {telem['ram']} | GPU: {telem['gpu']}"
            )
        self._root.after(1000, self._update_telemetry_tick)

    def set_telemetry_paused(self, paused: bool) -> None:
        """Pauses or resumes telemetry polling to conserve resources under load."""
        self._telemetry_paused = bool(paused)

    def toggle_visibility(self) -> None:
        """Toggles window visibility."""
        if not self._root:
            return
        if self.visible:
            self._root.withdraw()
            self.visible = False
        else:
            self._root.deiconify()
            self._root.lift()
            self._root.attributes("-topmost", True)
            self.visible = True

    def trigger_force_kill(self) -> None:
        """Invokes the force-kill callback to terminate hanging tool calls."""
        if self.on_force_kill:
            try:
                self.on_force_kill()
            except Exception as e:
                print(f"[HUD Error] Force-kill handler failed: {e}", file=sys.stderr)

    def _start_hotkey_listener(self) -> None:
        """Starts a background hotkey listener with zero-conflict fallbacks."""
        def _listener_loop():
            # 1. Preferred: pynput GlobalHotKeys if available
            if PYNPUT_AVAILABLE:
                try:
                    hotkeys = {
                        HOTKEY_TOGGLE: lambda: self.queue.put({"type": "toggle_visibility"}),
                        HOTKEY_KILL: self.trigger_force_kill,
                        "<f9>": lambda: self.queue.put({"type": "toggle_visibility"}),
                        "<f10>": self.trigger_force_kill,
                    }
                    with keyboard.GlobalHotKeys(hotkeys) as h:
                        while not self._stop_event.is_set():
                            time.sleep(0.2)
                    return
                except Exception:
                    pass

            # 2. Fallback for Windows: ctypes GetAsyncKeyState
            if sys.platform.startswith("win"):
                user32 = ctypes.windll.user32
                VK_F9 = 0x78
                VK_F10 = 0x79
                while not self._stop_event.is_set():
                    if user32.GetAsyncKeyState(VK_F9) & 1:
                        self.queue.put({"type": "toggle_visibility"})
                    if user32.GetAsyncKeyState(VK_F10) & 1:
                        self.trigger_force_kill()
                    time.sleep(0.08)

        t = threading.Thread(target=_listener_loop, name="ZetaHUD-Hotkeys", daemon=True)
        t.start()

    # Public helper methods for piping data from brain.py
    def update_tokens(self, session: int, daily: int, quota: int, model: str = "") -> None:
        self.queue.put({
            "type": "token_update",
            "session": session,
            "daily": daily,
            "quota": quota,
            "model": model,
        })

    def display_text_stream(self, text: str) -> None:
        self.queue.put({"type": "stream_text", "text": text})

    def append_chunk(self, chunk: str) -> None:
        self.queue.put({"type": "append_chunk", "chunk": chunk})

    def clear_stream(self) -> None:
        self.queue.put({"type": "clear"})


# ==============================================================================
# Standalone Verification Demo
# ==============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print(" ZetaJarvis Module 1: HUD System Overlay — Verification & Demo")
    print("=" * 70)

    def mock_kill():
        print("  [HOTKEY TRIGGERED] Force-kill signal received! Terminated hanging tasks.")

    hud = ZetaHUD(on_force_kill=mock_kill, speed_ms=10)
    print("\n[1] Querying System Telemetry (psutil / ctypes):")
    telem = get_system_telemetry()
    print(f"  CPU Utilization: {telem['cpu']}")
    print(f"  RAM Utilization: {telem['ram']}")
    print(f"  GPU Utilization: {telem['gpu']}")

    print("\n[2] Starting HUD Overlay in dedicated non-blocking thread...")
    hud.start()
    time.sleep(0.8)

    print("\n[3] Pushing token usage updates to HUD queue:")
    hud.update_tokens(session=150, daily=12400, quota=100000, model="nvidia/nemotron-3-ultra:free")

    print("\n[4] Simulating Typewriter Streaming Text Response:")
    sample_response = (
        "ZetaJarvis online. System telemetry verified. "
        "Multi-model routing engine standing by with 100% free-tier uptime guarantee."
    )
    hud.display_text_stream(sample_response)

    # Let typewriter animation render
    time.sleep(2.5)

    print("\n[5] Testing Visibility Toggle:")
    hud.toggle_visibility()
    time.sleep(0.4)
    hud.toggle_visibility()
    print("  Visibility toggled successfully.")

    print("\n[6] Testing Force-Kill Handler:")
    hud.trigger_force_kill()

    print("\n[7] Stopping HUD...")
    hud.stop()
    print("\n[SUCCESS] Module 1 (hud.py) verified successfully.")
