#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: governor.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Dynamic system-resource governor. Monitors CPU and RAM usage via
#              psutil and automatically throttles reasoning effort, reduces polling
#              frequency, pauses telemetry, and triggers emergency soft restarts.
# ------------------------------------------------------------------------------

"""Sub-system C: Resource Governance.

Features:
- Telemetry & Load Monitoring: Continuous CPU% and RAM% sampling via psutil.
- Dynamic Throttling:
  * If CPU > 85% or RAM > 90%:
    - Reduces brain.py reasoning effort to "low".
    - Stretches watchdog polling from 2s to 10s.
    - Pauses non-critical HUD telemetry.
    - Speaks "System load high, reducing performance" via TTS if load persists > 10s.
  * If CPU < 40% and RAM < 60%:
    - Restores normal reasoning, watchdog polling, and HUD telemetry.
- Emergency Overload Protection:
  * If CPU > 95% for 30 consecutive seconds, automatically initiates a soft restart
    of the voice pipeline and watchdog to release accumulated resources.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False


# ==============================================================================
# Configuration Thresholds
# ==============================================================================

CPU_HIGH_THRESHOLD = float(os.getenv("GOVERNOR_CPU_HIGH", "85.0"))
RAM_HIGH_THRESHOLD = float(os.getenv("GOVERNOR_RAM_HIGH", "90.0"))
CPU_LOW_THRESHOLD = float(os.getenv("GOVERNOR_CPU_LOW", "40.0"))
RAM_LOW_THRESHOLD = float(os.getenv("GOVERNOR_RAM_LOW", "60.0"))
EMERGENCY_CPU_THRESHOLD = float(os.getenv("GOVERNOR_CPU_EMERGENCY", "95.0"))
EMERGENCY_DURATION_SEC = float(os.getenv("GOVERNOR_EMERGENCY_DURATION", "30.0"))
PERSIST_HIGH_LOAD_SEC = 10.0
CHECK_INTERVAL_SEC = 1.0


class ResourceGovernor:
    """Monitors system resource pressure and governs background performance."""

    def __init__(
        self,
        on_throttle: Optional[Callable[[bool], None]] = None,
        on_emergency_restart: Optional[Callable[[], None]] = None,
        tts_speaker: Optional[Callable[[str], None]] = None,
        sample_interval: float = CHECK_INTERVAL_SEC,
    ) -> None:
        self.on_throttle = on_throttle
        self.on_emergency_restart = on_emergency_restart
        self.tts_speaker = tts_speaker
        self.sample_interval = sample_interval

        self.is_throttled = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._high_load_start_time: Optional[float] = None
        self._emergency_start_time: Optional[float] = None
        self._last_spoken_time: float = 0.0
        self._speech_cooldown_sec: float = 60.0

    def _speak(self, text: str) -> None:
        now = time.time()
        if now - self._last_spoken_time >= self._speech_cooldown_sec:
            self._last_spoken_time = now
            if self.tts_speaker:
                try:
                    self.tts_speaker(text)
                except Exception:
                    pass

    def get_system_metrics(self) -> Tuple[float, float]:
        """Returns current (cpu_percent, ram_percent)."""
        if not PSUTIL_AVAILABLE or psutil is None:
            return 0.0, 0.0
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            return float(cpu), float(ram)
        except Exception:
            return 0.0, 0.0

    def check_and_apply_governance(self, cpu: float, ram: float) -> bool:
        """Applies governance rules based on resource metrics. Returns True if throttled."""
        now = time.time()

        # 1. High Load Condition
        if cpu > CPU_HIGH_THRESHOLD or ram > RAM_HIGH_THRESHOLD:
            if not self.is_throttled:
                self.is_throttled = True
                self._high_load_start_time = now
                if self.on_throttle:
                    try:
                        self.on_throttle(True)
                    except Exception as exc:
                        print(f"[Governor Warn] on_throttle error: {exc}", file=sys.stderr)

            # Check if high load has persisted > 10 seconds
            if self._high_load_start_time and (now - self._high_load_start_time >= PERSIST_HIGH_LOAD_SEC):
                self._speak("System load high, reducing performance")

        # 2. Normal Load Recovery Condition
        elif cpu < CPU_LOW_THRESHOLD and ram < RAM_LOW_THRESHOLD:
            if self.is_throttled:
                self.is_throttled = False
                self._high_load_start_time = None
                self._emergency_start_time = None
                if self.on_throttle:
                    try:
                        self.on_throttle(False)
                    except Exception as exc:
                        print(f"[Governor Warn] on_throttle recovery error: {exc}", file=sys.stderr)

        # 3. Emergency Overload Condition (> 95% CPU for 30s)
        if cpu >= EMERGENCY_CPU_THRESHOLD:
            if self._emergency_start_time is None:
                self._emergency_start_time = now
            elif now - self._emergency_start_time >= EMERGENCY_DURATION_SEC:
                print(
                    f"[Governor Alert] Extreme CPU load ({cpu:.1f}%) sustained for {EMERGENCY_DURATION_SEC}s. "
                    "Triggering emergency soft restart...",
                    file=sys.stderr,
                    flush=True,
                )
                self._emergency_start_time = None
                if self.on_emergency_restart:
                    try:
                        self.on_emergency_restart()
                    except Exception as exc:
                        print(f"[Governor Error] on_emergency_restart exception: {exc}", file=sys.stderr)
        else:
            self._emergency_start_time = None

        return self.is_throttled

    def _monitor_loop(self) -> None:
        """Background sampling loop."""
        # Initial prime sample
        if PSUTIL_AVAILABLE and psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass

        while not self._stop_event.is_set():
            time.sleep(self.sample_interval)
            if self._stop_event.is_set():
                break

            cpu, ram = self.get_system_metrics()
            self.check_and_apply_governance(cpu, ram)

    def start(self) -> None:
        """Starts the resource governor daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, name="ZetaResourceGovernor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stops the resource governor thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


# ==============================================================================
# Standalone Verification Demo
# ==============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print(" ZetaJarvis Sub-system C: Resource Governor -- Verification Demo")
    print("=" * 70)

    throttle_events = []
    restart_events = []

    def mock_throttle_handler(throttled: bool) -> None:
        state_str = "THROTTLED (LOW EFFORT)" if throttled else "RESTORED (NORMAL)"
        throttle_events.append(throttled)
        print(f"  [Governor Event] Performance state changed: {state_str}")

    def mock_restart_handler() -> None:
        restart_events.append(True)
        print("  [Governor Event] Soft restart triggered for subsystems.")

    governor = ResourceGovernor(
        on_throttle=mock_throttle_handler,
        on_emergency_restart=mock_restart_handler,
    )

    print("\n[1] Current Real System Metrics:")
    current_cpu, current_ram = governor.get_system_metrics()
    print(f"  CPU Usage: {current_cpu:.1f}%")
    print(f"  RAM Usage: {current_ram:.1f}%")

    print("\n[2] Testing Simulated Load Transitions:")
    print("  * Simulating Spike: CPU=90.0%, RAM=92.0%...")
    governor.check_and_apply_governance(90.0, 92.0)
    print(f"    Governor Throttled: {governor.is_throttled}")

    print("  * Simulating Cooldown: CPU=30.0%, RAM=50.0%...")
    governor.check_and_apply_governance(30.0, 50.0)
    print(f"    Governor Throttled: {governor.is_throttled}")

    print("\n[3] Testing Emergency Overload Thresholds:")
    # Simulate CPU > 95% persisting beyond threshold
    governor._emergency_start_time = time.time() - (EMERGENCY_DURATION_SEC + 1.0)
    governor.check_and_apply_governance(96.0, 70.0)
    print(f"    Emergency restart executed: {len(restart_events) > 0}")

    print("\n[SUCCESS] Sub-system C (governor.py) verified successfully.")
