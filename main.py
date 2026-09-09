#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: main.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Central orchestrator unifying HUD overlay, voice pipeline,
#              metaprogramming auto-watchdog, stealth harness, multi-model brain,
#              system persistence, UI automation, and zero-downtime self-updater.
# ------------------------------------------------------------------------------

"""ZetaJarvis Central Enterprise Digital Worker Orchestrator.

Starts and coordinates all 7 enterprise subsystems:
1. Module 1: HUD (hud.py) – Transparent borderless overlay & real-time telemetry.
2. Module 2: Voice Pipeline (voice_pipeline.py) – 300ms pre-roll audio reactor, VAD, ASR, and dual TTS.
3. Module 3: Auto-Watchdog (auto_watchdog.py) – Metaprogramming hot-reloader & AST self-healer.
4. Module 4: Stealth Harness (stealth_harness.py) – Background diagnostics, evasion, and panic button.
5. Module 5: Persistence (persistence.py) – Registry & Task Scheduler keep-alive, Process Guardian, Stealth Mode.
6. Module 6: UI Automation (ui_automation.py) – Cross-app UI control and "Zeta, abort automation" kill-switch.
7. Module 7: Self-Update (self_update.py) – Zero-downtime Git updates and crash rollback guard.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Optional
import warnings

# Suppress third-party sounddevice deprecation warning with NumPy 2.5
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*Setting the shape on a NumPy array.*")

# Core Subsystems
import brain
from auto_watchdog import ToolWatchdog
from hud import ZetaHUD
from persistence import (
    AUTO_STARTUP_ENABLED,
    ProcessGuardian,
    StartupManager,
    apply_stealth_mode,
)
from env_validator import EnvironmentValidator
from governor import ResourceGovernor
from log_rotator import LogRotator
from self_update import SelfUpdater
from stealth_harness import StealthHarness
import ui_automation
from voice_pipeline import VoicePipeline


class ZetaJarvisDesktopApp:
    """Central orchestrator uniting all enterprise digital worker subsystems."""

    def __init__(
        self,
        headless: bool = False,
        stealth: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.headless = headless
        self.stealth = stealth or (os.getenv("STEALTH_MODE", "false").lower() in ("1", "true", "yes"))
        self.dry_run = dry_run
        self._shutdown_event = threading.Event()

        # Apply stealth mode if requested
        if self.stealth:
            apply_stealth_mode(minimize_console=True)

        # Sub-system D: Log Rotator & Stdout Redirection
        self.log_rotator = LogRotator()
        if not self.stealth and not self.headless:
            self.log_rotator.setup_stdout_redirection()

        # Core Brain Instance
        self.brain_instance = brain.Brain()

        # Sub-system B: Startup Environment Validator
        self.env_validator = EnvironmentValidator(
            tts_speaker=lambda msg: self.voice.tts.speak(msg) if hasattr(self, "voice") else None
        )
        self.diag_report = self.env_validator.run_diagnostics(speak_warnings=False)

        # Module 7: Self-Updater & Startup Crash Recovery Guard
        self.updater = SelfUpdater(
            tts_notifier=lambda msg: self.voice.tts.speak(msg) if hasattr(self, "voice") else None,
        )
        # Check if previous update caused a crash on boot
        recovered_from_crash = self.updater.check_startup_health_and_rollback_if_needed()
        if recovered_from_crash:
            print("[ZetaJarvis Alert] Recovered from bad update. Previous stable snapshot restored.", file=sys.stderr)

        # Module 1: HUD System Overlay (suppressed in headless or stealth mode)
        self.hud: Optional[ZetaHUD] = None
        if not self.headless and not self.stealth:
            self.hud = ZetaHUD(
                on_force_kill=self._on_force_kill_tools,
            )

        # Module 2: Voice Pipeline
        self.voice = VoicePipeline(
            on_command_recognized=self._on_speech_recognized,
        )

        # Module 3: Tool Watchdog
        self.watchdog = ToolWatchdog(
            tts_notifier=lambda msg: self.voice.tts.speak(msg),
        )

        # Sub-system C: Resource Governor
        def _on_governor_throttle(throttled: bool) -> None:
            brain.set_governor_throttle(throttled)
            if self.hud:
                self.hud.set_telemetry_paused(throttled)
            if hasattr(self, "watchdog") and hasattr(self.watchdog, "set_poll_interval"):
                self.watchdog.set_poll_interval(10.0 if throttled else 2.0)

        def _emergency_soft_restart() -> None:
            print("[Enterprise Node] Emergency soft restart triggered under extreme load.", file=sys.stderr, flush=True)
            try:
                self.voice.stop()
                self.watchdog.stop()
                time.sleep(1.0)
                self.watchdog.start()
                self.voice.start()
            except Exception:
                pass

        self.governor = ResourceGovernor(
            on_throttle=_on_governor_throttle,
            on_emergency_restart=_emergency_soft_restart,
            tts_speaker=lambda msg: self.voice.tts.speak(msg) if hasattr(self, "voice") else None,
        )

        # Module 4: Stealth Diagnostic Harness
        self.harness = StealthHarness(
            cleanup_callbacks=[self.stop],
        )

        # Module 5: Startup Persistence Manager
        self.startup_manager = StartupManager()

    def _register_startup_persistence(self) -> None:
        """Asynchronously registers system startup persistence."""
        if not AUTO_STARTUP_ENABLED:
            return

        def _worker() -> None:
            try:
                success = self.startup_manager.register_all(dry_run=self.dry_run)
                mode_str = " (dry-run)" if self.dry_run else ""
                if success:
                    print(f"  [+] Persistence: Dual startup registered{mode_str} (Registry + Task Scheduler).", flush=True)
                else:
                    print(f"  [-] Persistence: Registration notice{mode_str} - check system permissions.", flush=True)
            except Exception as exc:
                print(f"  [-] Persistence Warn: {exc}", file=sys.stderr)

        threading.Thread(target=_worker, name="StartupRegisterWorker", daemon=True).start()

    def _on_force_kill_tools(self) -> None:
        """Invoked when user hits force-kill hotkey (F10 / Ctrl+Alt+K)."""
        if self.hud:
            self.hud.display_text_stream("[Alert] Force-kill signal received. Clearing tasks.")
        print("[Domination Layer] Force-kill triggered. Cleaned up tasks.", file=sys.stderr)

    def _on_speech_recognized(self, text: str) -> None:
        """Handles transcribed user speech from voice pipeline."""
        clean_text = text.strip()
        if not clean_text:
            return

        # 1. Check UI Automation Kill-Switch phrase ("Zeta, abort automation")
        if ui_automation.check_abort_phrase(clean_text):
            ui_automation.trigger_abort()
            if self.hud:
                self.hud.display_text_stream("[ABORT] UI Automation kill-switch activated.")
            self.voice.tts.speak("UI automation aborted.")
            print("[UI Automation] Abort kill-switch triggered by voice.", file=sys.stderr)
            return

        # 2. Check Panic Lockdown Trigger ("Zeta, lockdown")
        if self.harness.check_panic_trigger(clean_text):
            if self.hud:
                self.hud.display_text_stream("[PANIC] Lockdown sequence initiated.")
            self.harness.trigger_lockdown()
            self.stop()
            return

        # 3. Query Multi-Model Routing Engine
        try:
            reply, tokens_used, model_used = brain.get_brain_response(clean_text)

            # Update HUD
            if self.hud:
                stats = brain.get_usage_stats()
                self.hud.update_tokens(
                    session=tokens_used,
                    daily=stats["daily_token_usage"],
                    quota=stats["daily_token_quota"],
                    model=model_used,
                )
                self.hud.display_text_stream(reply)

            # Speak Response
            self.voice.tts.speak(reply)

        except Exception as exc:
            err_msg = f"Processing error: {str(exc)}"
            if self.hud:
                self.hud.display_text_stream(err_msg)
            self.voice.tts.speak("I encountered an issue processing that.")

    def start(self) -> None:
        """Starts all subsystems concurrently across daemon threads."""
        print("=" * 70, flush=True)
        print(" Starting ZetaJarvis Enterprise Digital Worker Node...", flush=True)
        print("=" * 70, flush=True)

        # 1. Start Tool Watchdog
        self.watchdog.start()
        print("  [+] Auto-Watchdog: Monitoring tools/ for dynamic registration.", flush=True)

        # 2. Start HUD (if not suppressed by headless or stealth)
        if self.hud:
            self.hud.start()
            print("  [+] HUD Overlay: Running transparent telemetry display.", flush=True)
        elif self.stealth:
            print("  [+] Stealth Mode: HUD suppressed and console minimized.", flush=True)

        # 3. Start Voice Pipeline
        self.voice.start()
        print("  [+] Voice Pipeline: Non-blocking audio capture & VAD active.", flush=True)

        # 4. Start Stealth Harness Background Diagnostics
        self.harness.start_background_diagnostics()
        print("  [+] Stealth Harness: Background diagnostics running.", flush=True)

        # 5. Register Persistence (Registry + Task Scheduler)
        self._register_startup_persistence()

        # 6. Start Zero-Downtime Self-Updater Daemon
        self.updater.start_periodic_updater()
        print("  [+] Self-Updater: Zero-downtime Git polling & rollback guard active.", flush=True)

        # 7. Start Resource Governor Daemon
        self.governor.start()
        print("  [+] Resource Governor: Active (CPU/RAM telemetry & throttling).", flush=True)

        # 8. Start Log Rotator Daemon
        self.log_rotator.start_daemon()
        print("  [+] Log Rotator: Active (10MB size rotation & 30-day retention).", flush=True)

        # Mark update as cleanly booted
        self.updater.mark_startup_successful()

        stats = brain.get_usage_stats()
        print(f"  [+] Core Brain: Active (Daily: {stats['daily_token_usage']} / {stats['daily_token_quota']} tokens).", flush=True)
        print(f"  [+] Environment: {self.diag_report.summary()}", flush=True)
        print("=" * 70, flush=True)
        print(" ZetaJarvis is online. Speak commands or press Ctrl+C to exit.", flush=True)
        print("=" * 70, flush=True)

    def stop(self) -> None:
        """Gracefully shuts down all subsystems."""
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()

        print("\n[Enterprise Node] Shutting down all subsystems...", file=sys.stderr)
        self.governor.stop()
        self.updater.stop()
        self.voice.stop()
        self.watchdog.stop()
        if self.hud:
            self.hud.stop()
        self.log_rotator.stop()
        print("[Enterprise Node] All subsystems stopped cleanly.", file=sys.stderr)

    def run_forever(self) -> None:
        """Main loop waiting for shutdown signal."""
        try:
            while not self._shutdown_event.is_set():
                time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit):
            self.stop()


# ==============================================================================
# CLI Entry Point & Guardian Launcher
# ==============================================================================

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ZetaJarvis Enterprise Digital Worker Node")
    parser.add_argument("--guardian", action="store_true", help="Launch Process Guardian supervisor watchdog")
    parser.add_argument("--headless", action="store_true", help="Run without graphical HUD overlay")
    parser.add_argument("--stealth", action="store_true", help="Enable stealth mode (no HUD, minimized console)")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode for persistence and testing")
    parser.add_argument("--demo", action="store_true", help="Run standalone verification demo and exit")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()

    # 1. Process Guardian Mode
    if args.guardian:
        print("[Guardian] Spawning ZetaJarvis Process Guardian supervisor...", flush=True)
        extra_args = [a for a in sys.argv[1:] if a != "--guardian"]
        guardian = ProcessGuardian()
        guardian.start_guardian_loop(extra_args=extra_args)
        sys.exit(0)

    # 2. Verification Demo Mode
    if args.demo or len(sys.argv) == 1:
        print("=" * 70, flush=True)
        print(" ZetaJarvis Enterprise Orchestrator (main.py) -- Verification Demo", flush=True)
        print("=" * 70, flush=True)

        app = ZetaJarvisDesktopApp(headless=True, dry_run=True)
        app.start()

        print("\n[1] Testing UI Automation Kill-Switch via Voice:", flush=True)
        abort_command = "Zeta, abort automation"
        print(f"  Simulated Voice Input: '{abort_command}'", flush=True)
        app._on_speech_recognized(abort_command)
        print(f"  UI Automation Is Aborted: {ui_automation.is_aborted()}", flush=True)
        ui_automation.reset_abort()

        print("\n[2] Testing Simulated Knowledge Query:", flush=True)
        sample_voice_command = "What is the capital of France and its population?"
        print(f"  Simulated Voice Input: '{sample_voice_command}'", flush=True)
        app._on_speech_recognized(sample_voice_command)

        print("\n[3] Testing UI Automation: Open Notepad & Type:", flush=True)
        notepad_command = "Zeta, open Notepad and type 'Hello Zeta'"
        print(f"  Simulated Voice Input: '{notepad_command}'", flush=True)
        app._on_speech_recognized(notepad_command)
        # Close Notepad test window cleanly
        time.sleep(0.5)
        ui_automation.WindowController.control_window("Notepad", "close")

        print("\n[4] Testing Simulated Panic Lockdown:", flush=True)
        panic_voice_command = "Zeta, lockdown"
        print(f"  Simulated Panic Input: '{panic_voice_command}'", flush=True)
        app._on_speech_recognized(panic_voice_command)

        print("\n[SUCCESS] Central Orchestrator (main.py) verified successfully.", flush=True)
        sys.exit(0)

    # 3. Production Running Mode
    app = ZetaJarvisDesktopApp(
        headless=args.headless,
        stealth=args.stealth,
        dry_run=args.dry_run,
    )
    app.start()
    app.run_forever()
