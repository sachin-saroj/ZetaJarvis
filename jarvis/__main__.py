#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: jarvis/__main__.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: Links microphone, recognition, wake word, brain, and TTS into loop.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""ZetaJarvis Main Program: links microphone, recognition, wake word, brain, and TTS together into a loop.

Run:
    python -m jarvis            # With desktop glowing orb pet (default)
    python -m jarvis --no-pet   # Command-line only, no window

State Machine:
    idle: Listen continuously until wake word "Jarvis" is heard (or pet is clicked)
    active: Each heard phrase is processed by LLM; returns to idle after silent timeout
Desktop pet (GUI) runs on the main thread, while the voice assistant runs on a background thread.
Communication is thread-safe.
"""

from __future__ import annotations

import difflib
import queue
import re
import subprocess
import sys
import threading
import time

from . import asr, config, tts
from .audio import Microphone
from .brain import Brain

_PUNCT = " ，。！？、,.!?～~"


# ---- Wake Word Detection: Fuzzy English Matching --------------------------------------------

def _wake_match(text: str) -> tuple[bool, int]:
    """Checks if the text contains any wake word using exact and fuzzy matching.
    Returns (is_match, end_character_index).
    """
    low = text.lower()
    
    # 1. Exact substring match first (highly reliable)
    for w in config.WAKE_WORDS:
        w_clean = w.lower()
        idx = low.find(w_clean)
        if idx != -1:
            return True, idx + len(w_clean)
            
    # 2. Fuzzy word-by-word matching using SequenceMatcher (useful for Whisper phonetic misspellings)
    pattern = re.compile(r"\b[a-zA-Z]+\b")
    best_ratio = 0.0
    best_end = 0
    
    for match in pattern.finditer(text):
        word = match.group()
        word_clean = word.lower()
        end_pos = match.end()
        
        for w in config.WAKE_WORDS:
            w_clean = w.lower()
            ratio = difflib.SequenceMatcher(None, word_clean, w_clean).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_end = end_pos
                
    return best_ratio >= config.WAKE_SIM, best_end


def _has_wake_word(text: str) -> bool:
    return _wake_match(text)[0]


def _strip_wake_word(text: str) -> str:
    ok, end = _wake_match(text)
    rest = text[end:] if ok else text
    return rest.strip(_PUNCT)


def _cue() -> None:
    """Wake alert sound."""
    if config.IS_WINDOWS:
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_OK)
        except Exception:  # noqa: BLE001
            pass
        return
    subprocess.Popen(
        ["afplay", "/System/Library/Sounds/Glass.aiff"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# ---- UI Abstraction: CliUI / DesktopPet share the same interface --------------------------

class CliUI:
    """Command-line UI: logs directly to the console."""

    def set_state(self, state: str) -> None: ...
    def log(self, text: str) -> None: print(text)
    def heard(self, text: str) -> None: ...
    def reply(self, text: str) -> None: print(f"🤖 ZetaJarvis: {text}\n")
    def poll_talk(self) -> bool: return False


# ---- Voice Assistant Main Loop (Runs on background thread) -------------------------------

def run_assistant(ui, stop: threading.Event) -> None:
    api_key = config.load_api_key()          # Validated in main(), guaranteed to exist here
    ui.log("⏳ Loading speech recognition model (will download on first run, please wait)...")
    asr.load()

    # Connect MCP tools (optional, configured in mcp.json; startup failures do not affect main program)
    from .mcp_bridge import McpBridge, load_config
    mcp = None
    mcp_cfg = load_config()
    if mcp_cfg:
        ui.log("⏳ Connecting to MCP tools (will download servers on first run, please wait)...")
        mcp = McpBridge()
        mcp.start(mcp_cfg, log=ui.log)

    brain = Brain(api_key, mcp=mcp)

    ui.log("⏳ Calibrating microphone ambient noise, please remain quiet...")
    with Microphone() as mic:
        mic.on_speech_start = lambda: ui.set_state("listening")
        ui.log(f"✓ Ready! Say \"Jarvis\" or click the desktop pet to wake me. (Noise threshold: {mic.threshold:.0f})\n")
        ui.log("💬 Tip: Type text in the input box at the bottom to talk to ZetaJarvis!\n")

        awake_until = 0.0
        for audio in mic.segments():
            if stop.is_set():
                break

            # Check for text input from UI
            text_input = ui.poll_text_input() if hasattr(ui, 'poll_text_input') else None
            if text_input:
                # Process text input as command
                ui.set_state("thinking")
                ui.log(f"💭 Processing: {text_input}")
                try:
                    reply = brain.ask(text_input)
                except Exception as e:
                    print(f"⚠️ Error: {e}")
                    reply = "Sorry, I ran into an issue here."
                ui.reply(reply)
                ui.set_state("speaking")
                tts.speak(reply, blocking=True)
                ui.set_state("idle")
                awake_until = time.time() + config.ACTIVE_TIMEOUT
                continue

            clicked = ui.poll_talk()             # Click pet = force enter active state
            if clicked:
                awake_until = time.time() + config.ACTIVE_TIMEOUT

            # Quota saving + standby privacy: Standby only uses local listening for wake words (free, private);
            # commands after wake use iFlytek Cloud (more accurate).
            awake = time.time() < awake_until
            res = asr.transcribe(audio, cloud=awake)
            text = res.text

            if not text:
                if not awake:
                    ui.set_state("idle")
                continue
            ui.log(f"🎤 Heard: {text}")

            if not awake:
                # Standby strict filtering: noise, low confidence, or too short input are ignored
                if (res.no_speech > config.WAKE_MAX_NO_SPEECH
                        or res.avg_logprob < config.WAKE_MIN_LOGPROB
                        or len(text) < config.WAKE_MIN_LEN):
                    ui.set_state("idle")
                    continue
                if not _has_wake_word(text):
                    ui.set_state("idle")
                    continue
                _cue()
                command = _strip_wake_word(text)
                if not command:                    # Only called the name, responds and waits for commands
                    ui.set_state("speaking")
                    tts.speak("I am here", blocking=True)
                    mic.flush()
                    ui.set_state("idle")
                    awake_until = time.time() + config.ACTIVE_TIMEOUT
                    continue
                # "Jarvis + command" in a single phrase: standby is transcribed locally, command part re-transcribed via iFlytek cloud for higher accuracy
                if config.ASR_BACKEND == "xfyun":
                    cloud_res = asr.transcribe(audio, cloud=True)
                    if cloud_res.text:
                        command = _strip_wake_word(cloud_res.text)
            else:
                # Active state also filters noise to avoid treating background noise/TTS echo as commands
                if (res.no_speech > config.WAKE_MAX_NO_SPEECH
                        or res.avg_logprob < config.WAKE_MIN_LOGPROB):
                    continue
                command = text

            ui.heard(command)
            ui.set_state("thinking")
            ui.log(f"💭 Processing: {command}")

            # Streaming pipeline: background thread pushes completed sentences into queue; main thread speaks them.
            # This overlaps LLM generation with TTS synthesis/playback, reducing speech latency.
            sq: "queue.Queue[tuple[str, str]]" = queue.Queue()

            def _produce(cmd: str = command) -> None:
                try:
                    for sent in brain.ask_stream(cmd):
                        sq.put(("s", sent))
                except Exception as e:  # noqa: BLE001
                    sq.put(("err", str(e)))
                finally:
                    sq.put(("end", ""))

            threading.Thread(target=_produce, daemon=True).start()

            parts: list[str] = []
            while True:
                kind, val = sq.get()
                if kind == "end":
                    break
                if kind == "err":
                    ui.log(f"  Brain error: {val}")
                    continue
                if not parts:
                    ui.set_state("speaking")       # Switch state to speaking only when the first sentence arrives
                parts.append(val)
                ui.reply(val)
                tts.speak(val, blocking=True)      # Speak sentence by sentence without interruption

            reply = "".join(parts)
            if not reply:                          # No text produced throughout (error, etc.)
                ui.set_state("speaking")
                tts.speak("Sorry, I ran into an issue here.", blocking=True)
            ui.log(f"🤖 ZetaJarvis: {reply}\n")

            mic.flush()                            # Flush echo recorded during speaking to prevent self-looping
            ui.set_state("idle")
            awake_until = time.time() + config.ACTIVE_TIMEOUT


def main() -> int:
    # Validate Python version
    if sys.version_info < (3, 10) or sys.version_info >= (3, 13):
        print(f"⚠️  Warning: ZetaJarvis is optimized and tested for Python 3.10 - 3.12.\n"
              f"   Your current version is {sys.version_info.major}.{sys.version_info.minor}. Proceeding with caution...\n",
              file=sys.stderr)

    use_pet = "--no-pet" not in sys.argv[1:]

    if not config.LLM_BASE_URL:
        print("✗ API Gateway URL is not configured.", file=sys.stderr)
        print("  Please write your API Gateway URL in base_url.txt (e.g. https://your-gateway/v1).",
              file=sys.stderr)
        return 1
    if not config.load_api_key():
        print("✗ API Key not found.", file=sys.stderr)
        print("  Please write your API key in api_key.txt (or set environment variable JARVIS_API_KEY).",
              file=sys.stderr)
        return 1
    print(f"🧠 Brain: {config.MODEL}  @ {config.LLM_BASE_URL}", file=sys.stderr)
    _asr = ("iFlytek Cloud Speech Transcription" if config.ASR_BACKEND == "xfyun"
            else f"Local Whisper-{config.WHISPER_MODEL}")
    print(f"🎙️ ASR: {_asr}", file=sys.stderr)

    if use_pet:
        try:
            from .pet import DesktopPet
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Desktop pet failed to load, switching to command-line mode: {e}")
            use_pet = False

    stop = threading.Event()
    if use_pet:
        pet = DesktopPet()
        worker = threading.Thread(target=run_assistant, args=(pet, stop), daemon=True)
        worker.start()
        try:
            pet.run()                              # Main thread runs the GUI; closing the window exits
        finally:
            stop.set()
    else:
        run_assistant(CliUI(), stop)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n👋 ZetaJarvis exited.")
