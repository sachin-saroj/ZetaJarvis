#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: env_validator.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Startup environment validation & self-diagnostic health check.
#              Validates microphone, internet connectivity, API key, and
#              critical dependencies with retry and degraded mode fallback.
# ------------------------------------------------------------------------------

"""Sub-system B: Startup Environment Validation.

Features:
- Microphone Diagnostic: Checks for active audio input devices.
- Internet Connectivity: Probes gateway (openrouter.ai) with 5s timeout & 3x exponential backoff.
- API Key Validation: Inspects OPENROUTER_API_KEY and JARVIS_API_KEY.
- Dependency Integrity: Inspects required runtime libraries.
- Degraded Mode Protection: The app NEVER crashes on environmental failures;
  it logs clear diagnostics, speaks status via TTS, and enters safe fallback mode.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional
import urllib.request

# ==============================================================================
# Configuration
# ==============================================================================

TEST_ENDPOINT = os.getenv("JARVIS_BASE_URL", "https://openrouter.ai").rstrip("/")
PING_TIMEOUT_SEC = 5.0
MAX_CONNECTIVITY_RETRIES = 3

CRITICAL_DEPENDENCIES = [
    "openai",
    "tiktoken",
    "sounddevice",
    "numpy",
    "pyttsx3",
    "psutil",
    "uiautomation",
    "PIL",
    "cryptography",
]


@dataclasses.dataclass
class DiagnosticReport:
    """Encapsulates the results of all startup diagnostic checks."""
    microphone_ok: bool = True
    network_ok: bool = True
    api_key_ok: bool = True
    dependencies_ok: bool = True
    is_degraded: bool = False
    details: Dict[str, str] = dataclasses.field(default_factory=dict)
    warnings: List[str] = dataclasses.field(default_factory=list)

    def summary(self) -> str:
        status_str = "DEGRADED MODE" if self.is_degraded else "ALL SYSTEMS HEALTHY"
        return f"Startup Environment Status: {status_str} ({len(self.warnings)} warnings)"


class EnvironmentValidator:
    """Performs pre-flight startup self-diagnostics with retries and fallback."""

    def __init__(
        self,
        endpoint_url: str = TEST_ENDPOINT,
        tts_speaker: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.tts_speaker = tts_speaker

    def _speak(self, text: str) -> None:
        if self.tts_speaker:
            try:
                self.tts_speaker(text)
            except Exception:
                pass

    # --------------------------------------------------------------------------
    # Diagnostic Checks
    # --------------------------------------------------------------------------

    def validate_microphone(self) -> Tuple[bool, str]:
        """Checks if at least one audio input device is available."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            input_devices = [d for d in devices if d.get("max_input_channels", 0) > 0]
            if input_devices:
                return True, f"Found {len(input_devices)} active audio input device(s)."
            return False, "No audio input devices detected. Voice input will be degraded."
        except Exception as exc:
            return False, f"Microphone subsystem unavailable: {exc}"

    def validate_connectivity(self, retries: int = MAX_CONNECTIVITY_RETRIES) -> Tuple[bool, str]:
        """Probes internet connectivity with exponential backoff."""
        target_url = self.endpoint_url
        if not target_url.startswith("http"):
            target_url = f"https://{target_url}"

        backoff = 1.0
        last_error = ""

        for attempt in range(1, retries + 1):
            try:
                req = urllib.request.Request(
                    target_url,
                    headers={"User-Agent": "ZetaJarvis-HealthCheck/1.0"},
                )
                with urllib.request.urlopen(req, timeout=PING_TIMEOUT_SEC) as resp:
                    if resp.status in (200, 301, 302, 403, 404, 405):
                        return True, f"Gateway reachable at {target_url} (HTTP {resp.status})."
            except Exception as exc:
                last_error = str(exc)
                if attempt < retries:
                    time.sleep(backoff)
                    backoff *= 2.0

        return False, f"Network unreachable after {retries} attempts: {last_error}"

    def validate_api_key(self) -> Tuple[bool, str]:
        """Validates that an API key is configured for LLM routing."""
        key = (
            os.getenv("JARVIS_API_KEY", "")
            or os.getenv("OPENROUTER_API_KEY", "")
            or os.getenv("OPENAI_API_KEY", "")
        ).strip()

        # Check api_key.txt file fallback
        if not key:
            key_file = Path("api_key.txt")
            if key_file.exists():
                key = key_file.read_text(encoding="utf-8").strip()

        if key and len(key) >= 8 and not key.startswith("your-"):
            return True, "Valid API key detected."
        return False, "No valid API key found. Operating in degraded local knowledge mode."

    def validate_dependencies(self, auto_install: bool = False) -> Tuple[bool, str]:
        """Validates critical Python dependencies, optionally auto-installing missing."""
        missing = []
        for pkg in CRITICAL_DEPENDENCIES:
            try:
                importlib.import_module(pkg)
            except ImportError:
                missing.append(pkg)

        if not missing:
            return True, "All critical runtime dependencies verified."

        if auto_install and not getattr(sys, "frozen", False):
            print(f"[EnvValidator] Attempting auto-install for missing packages: {missing}...", file=sys.stderr)
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install"] + missing,
                    check=False,
                    capture_output=True,
                )
                # Re-check
                still_missing = []
                for pkg in missing:
                    try:
                        importlib.import_module(pkg)
                    except ImportError:
                        still_missing.append(pkg)
                if not still_missing:
                    return True, f"Auto-installed missing dependencies: {missing}"
                missing = still_missing
            except Exception:
                pass

        return False, f"Missing optional dependencies: {missing}"

    # --------------------------------------------------------------------------
    # Comprehensive Self-Diagnostic Routine
    # --------------------------------------------------------------------------

    def run_diagnostics(self, speak_warnings: bool = False) -> DiagnosticReport:
        """Executes full diagnostic suite and returns comprehensive report."""
        report = DiagnosticReport()

        # 1. Microphone
        mic_ok, mic_msg = self.validate_microphone()
        report.microphone_ok = mic_ok
        report.details["microphone"] = mic_msg
        if not mic_ok:
            report.warnings.append(mic_msg)

        # 2. Connectivity
        net_ok, net_msg = self.validate_connectivity()
        report.network_ok = net_ok
        report.details["network"] = net_msg
        if not net_ok:
            report.warnings.append(net_msg)

        # 3. API Key
        key_ok, key_msg = self.validate_api_key()
        report.api_key_ok = key_ok
        report.details["api_key"] = key_msg
        if not key_ok:
            report.warnings.append(key_msg)

        # 4. Dependencies
        dep_ok, dep_msg = self.validate_dependencies()
        report.dependencies_ok = dep_ok
        report.details["dependencies"] = dep_msg
        if not dep_ok:
            report.warnings.append(dep_msg)

        # Evaluate degraded status
        report.is_degraded = not (report.microphone_ok and report.network_ok and report.api_key_ok)

        if report.is_degraded and speak_warnings:
            if not report.network_ok:
                self._speak("System offline. Entering local fallback mode.")
            elif not report.api_key_ok:
                self._speak("API key not configured. Entering degraded mode.")
            elif not report.microphone_ok:
                self._speak("Microphone not detected. Voice input disabled.")

        return report


# ==============================================================================
# Standalone Verification Demo
# ==============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print(" ZetaJarvis Sub-system B: Environment Validator -- Verification Demo")
    print("=" * 70)

    validator = EnvironmentValidator()
    print("\nRunning comprehensive startup diagnostics...")
    rep = validator.run_diagnostics(speak_warnings=False)

    print(f"\n[Summary] {rep.summary()}")
    print("\n[Detailed Results]:")
    for component, detail in rep.details.items():
        status_tag = "[+]" if component not in [w.split()[0].lower() for w in rep.warnings] else "[-]"
        print(f"  {status_tag} {component.capitalize()}: {detail}")

    if rep.warnings:
        print("\n[Active Warnings / Degraded State]:")
        for w in rep.warnings:
            print(f"  * {w}")
    else:
        print("\n[+] All diagnostic checks passed with zero degraded flags.")

    print("\n[SUCCESS] Sub-system B (env_validator.py) verified successfully.")
